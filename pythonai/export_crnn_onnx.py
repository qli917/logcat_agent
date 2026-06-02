import os
import sys

import torch

from train_crnn import CRNN


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PT_PATH = os.path.join(BASE_DIR, "timestamp_crnn_best.pt")
DEFAULT_ONNX_PATH = os.path.join(BASE_DIR, "timestamp_crnn_best.onnx")


def main():
    pt_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PT_PATH
    onnx_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_ONNX_PATH

    checkpoint = torch.load(pt_path, map_location="cpu")
    alphabet = checkpoint["alphabet"]
    img_h = int(checkpoint["img_h"])
    img_w = int(checkpoint["img_w"])

    model = CRNN(num_classes=len(alphabet) + 1)
    model.load_state_dict(checkpoint["model"])
    model.eval()

    dummy = torch.randn(1, 1, img_h, img_w)
    torch.onnx.export(
        model,
        dummy,
        onnx_path,
        input_names=["image"],
        output_names=["logits"],
        opset_version=17,
        external_data=False,
        dynamic_axes={
            "image": {0: "batch"},
            "logits": {1: "batch"},
        },
    )

    print(f"exported: {onnx_path}")
    print(f"alphabet: {alphabet}")
    print(f"img_h: {img_h}, img_w: {img_w}")


if __name__ == "__main__":
    main()
