"""Likeness worker: runs in ComfyUI's Python (torch + transformers), talks JSON lines on stdin/stdout.

It finds a subject in a picture with an open-vocabulary detector (OWLv2, by its plain noun:
"man", "biplane", "steam engine"), crops it, and compares the crop with the same crop of the
subject's reference portrait using DINOv2 patch features (symmetric best-match similarity, 0-1).
People are compared by the head (clothes may change between scenes; no visible head = not
checked), everything else by the whole subject. Started by pipeline/likeness.py; not imported
by the studio itself.

Requests:  {"op": "inspect", "image": path, "noun": "man"}
           {"op": "score", "image": path, "reference": path, "noun": "man", "person": true, "min_area": 0.012}
"""
from __future__ import annotations

import json
import sys

import torch
from PIL import Image, ImageOps

DETECT_THRESHOLD = 0.10
HEAD_QUERIES = ["a head", "a face"]


class Likeness:
    def __init__(self, detector: str, embedder: str, device: str) -> None:
        from transformers import AutoImageProcessor, AutoModel, Owlv2ForObjectDetection, Owlv2Processor
        torch.set_num_threads(max(1, min(16, torch.get_num_threads())))
        self.device = device
        self.det_proc = Owlv2Processor.from_pretrained(detector)
        self.det = Owlv2ForObjectDetection.from_pretrained(detector).to(device).eval()
        self.emb_proc = AutoImageProcessor.from_pretrained(embedder)
        self.emb = AutoModel.from_pretrained(embedder).to(device).eval()
        self._ref_cache: dict = {}

    # ---- detection -------------------------------------------------------------------------
    @torch.inference_mode()
    def detect(self, img: Image.Image, queries: list[str], threshold: float = DETECT_THRESHOLD):
        """[(box(x0,y0,x1,y1), score)] best first, in image pixels."""
        w, h = img.size
        inputs = self.det_proc(text=[queries], images=img, return_tensors="pt").to(self.device)
        out = self.det(**inputs)
        side = max(w, h)                       # OWLv2 pads to a square at the bottom/right
        res = self.det_proc.image_processor.post_process_object_detection(
            out, threshold=threshold, target_sizes=[(side, side)])[0]
        found = []
        for box, score in zip(res["boxes"].tolist(), res["scores"].tolist()):
            x0, y0, x1, y1 = max(0, box[0]), max(0, box[1]), min(w, box[2]), min(h, box[3])
            if x1 - x0 > 4 and y1 - y0 > 4:
                found.append(((x0, y0, x1, y1), float(score)))
        found.sort(key=lambda f: -f[1])
        return _nms(found)

    def subject_boxes(self, img: Image.Image, noun: str):
        return self.detect(img, [f"a {noun}", f"an illustration of a {noun}"])

    def head_box(self, img: Image.Image, box):
        crop = img.crop(tuple(int(v) for v in box))
        heads = self.detect(crop, HEAD_QUERIES, threshold=0.12)
        if not heads:
            return None
        (x0, y0, x1, y1), _ = heads[0]
        return (box[0] + x0, box[1] + y0, box[0] + x1, box[1] + y1)

    # ---- features --------------------------------------------------------------------------
    @torch.inference_mode()
    def embed(self, img: Image.Image, box) -> torch.Tensor:
        """Normalised DINOv2 patch features of the crop (one row per image patch)."""
        x0, y0, x1, y1 = box
        pad = 0.06 * max(x1 - x0, y1 - y0)
        crop = img.crop((int(max(0, x0 - pad)), int(max(0, y0 - pad)),
                         int(min(img.width, x1 + pad)), int(min(img.height, y1 + pad))))
        side = max(crop.size)
        square = ImageOps.pad(crop, (side, side), color=(128, 128, 128))   # no centre-crop cut-offs
        inputs = self.emb_proc(images=square.resize((224, 224)), return_tensors="pt",
                               do_center_crop=False, do_resize=False).to(self.device)
        out = self.emb(**inputs).last_hidden_state[0]
        return torch.nn.functional.normalize(out[1:], dim=1)

    @staticmethod
    def similarity(a: torch.Tensor, b: torch.Tensor) -> float:
        """Symmetric best-match: every patch finds its most similar patch in the other crop.
        Robust to pose and partial occlusion, unlike one global vector (calibrated 2026-11-26:
        same person's head 0.76-0.93, different people <= 0.68; same ship ~0.78, other ships <= 0.56)."""
        sim = a @ b.T
        return float((sim.max(1).values.mean() + sim.max(0).values.mean()) / 2)

    def reference(self, path: str, noun: str, person: bool):
        key = (path, noun, person)
        if key not in self._ref_cache:
            img = Image.open(path).convert("RGB")
            boxes = self.subject_boxes(img, noun)
            box = boxes[0][0] if boxes else (0, 0, img.width, img.height)
            head = self.head_box(img, box) if person else None
            self._ref_cache[key] = (self.embed(img, box), self.embed(img, head) if head else None)
        return self._ref_cache[key]

    # ---- requests --------------------------------------------------------------------------
    def inspect(self, image: str, noun: str) -> dict:
        img = Image.open(image).convert("RGB")
        boxes = self.subject_boxes(img, noun)
        if not boxes:
            return {"found": 0, "best": 0.0, "quality": 0.0}
        (x0, y0, x1, y1), best = boxes[0]
        area = (x1 - x0) * (y1 - y0) / (img.width * img.height)
        extra = sum(1 for _, s in boxes[1:] if s > 0.5 * best)
        margin = 0.01 * max(img.size)
        cut = x0 < margin or y0 < margin or x1 > img.width - margin or y1 > img.height - margin
        size_ok = 0.08 <= area <= 0.85
        quality = best - 0.15 * extra - (0.2 if cut else 0.0) - (0.0 if size_ok else 0.15)
        return {"found": len(boxes), "best": round(best, 3), "area": round(area, 3), "extra": extra,
                "cut": cut, "quality": round(quality, 3)}

    def score(self, image: str, reference: str, noun: str, person: bool, min_area: float) -> dict:
        img = Image.open(image).convert("RGB")
        ref_fig, ref_head = self.reference(reference, noun, person)
        boxes = self.subject_boxes(img, noun)[:5]
        if not boxes:
            return {"status": "not_found", "score": None}
        total = img.width * img.height
        large = [(b, s) for b, s in boxes if (b[2] - b[0]) * (b[3] - b[1]) / total >= min_area]
        if not large:
            return {"status": "too_small", "score": None}
        best = {"status": "no_face" if person else "checked", "score": None if person else -1.0}
        for box, det in large:
            fig = self.similarity(self.embed(img, box), ref_fig)
            head = None
            if person and ref_head is not None:
                hb = self.head_box(img, box)
                if hb and (hb[3] - hb[1]) >= 40:
                    head = self.similarity(self.embed(img, hb), ref_head)
            if person and head is None:            # a body alone says little about who it is
                continue
            value = head if person else fig
            if best["score"] is None or value > best["score"]:
                best = {"status": "checked", "score": round(value, 3), "figure": round(fig, 3),
                        "head": None if head is None else round(head, 3), "box": [round(v) for v in box],
                        "by": "head" if person else "figure"}
        return best


def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def _nms(found, iou: float = 0.5):
    kept = []
    for box, score in found:
        if all(_iou(box, k[0]) < iou for k in kept):
            kept.append((box, score))
    return kept


def main() -> None:
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    model = Likeness(args.get("detector", "google/owlv2-base-patch16-ensemble"),
                     args.get("embedder", "facebook/dinov2-base"), args.get("device", "cpu"))
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            if req["op"] == "inspect":
                res = model.inspect(req["image"], req["noun"])
            elif req["op"] == "score":
                res = model.score(req["image"], req["reference"], req["noun"], bool(req.get("person")),
                                  float(req.get("min_area", 0.012)))
            else:
                res = {"error": f"unknown op {req['op']}"}
        except Exception as exc:                      # report, keep serving
            res = {"error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(res), flush=True)


if __name__ == "__main__":
    main()
