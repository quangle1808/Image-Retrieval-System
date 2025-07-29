import torch
import clip
from PIL import Image
import requests
from io import BytesIO

device = "cuda" if torch.cuda.is_available() else "cpu"
model, preprocess = clip.load("ViT-B/32", device=device)
total_params = sum(p.numel() for p in model.parameters())
print(f"Number of parameters in CLIP model: {total_params:,}")


def encode_text(text):
    print("encode_text is running on device:", device)
    if device == "cuda":
        print("CUDA device name:", torch.cuda.get_device_name(0))
    with torch.no_grad():
        return model.encode_text(clip.tokenize([text]).to(device)).cpu()

def encode_image_from_url(url, token=None):
    print("encode_image_from_url is running on device:", device)
    if device == "cuda":
        print("CUDA device name:", torch.cuda.get_device_name(0))
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.get(url, headers=headers)
    image = preprocess(Image.open(BytesIO(response.content))).unsqueeze(0).to(device)
    with torch.no_grad():
        return model.encode_image(image).cpu()
