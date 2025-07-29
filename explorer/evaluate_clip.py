# import os
# import numpy as np
# from explorer.clip_model import encode_text, encode_image_from_url
#
# # ------------------------------------------
# # 1. Prepare your test data
# # ------------------------------------------
# # Replace with your real data. Example:
# test_pairs = [
#     # (query_text, ground_truth_image_id)
#     ("a dog running", "imgid123456"),
#     ("a red car", "imgid789012"),
#     # Add more pairs from your own OneDrive data and annotations
# ]
#
# all_images = [
#     # {'id': ..., 'name': ...}
#     {'id': "imgid123456", 'name': "dog1.jpg"},
#     {'id': "imgid789012", 'name': "car_red.jpg"},
#     # Add all available images you want to use as candidates
# ]
#
# # You need a valid Microsoft Graph API token here
# token = "YOUR_ONEDRIVE_ACCESS_TOKEN"  # Replace this with your access token
#
# # ------------------------------------------
# # 2. Hits@10 Evaluation Function
# # ------------------------------------------
# def evaluate_hits_at_10(test_pairs, all_images, token):
#     hits = 0
#     n_total = len(test_pairs)
#
#     # Precompute and cache all image embeddings
#     image_embeddings = {}
#     for img in all_images:
#         img_id = img['id']
#         img_url = f"https://graph.microsoft.com/v1.0/me/drive/items/{img_id}/content"
#         print(f"Encoding image: {img['name']} (ID: {img_id})")
#         try:
#             image_vec = encode_image_from_url(img_url, token).numpy().flatten()
#             image_vec = image_vec / np.linalg.norm(image_vec)
#             image_embeddings[img_id] = image_vec
#         except Exception as e:
#             print(f"Failed to encode image {img['name']} ({img_id}): {e}")
#             continue
#
#     # For each query, check if ground-truth image is in top 10
#     for idx, (query_text, gt_image_id) in enumerate(test_pairs):
#         print(f"\n[{idx+1}/{n_total}] Query: {query_text} (Ground Truth ID: {gt_image_id})")
#         try:
#             text_vec = encode_text(query_text).numpy().flatten()
#             text_vec = text_vec / np.linalg.norm(text_vec)
#         except Exception as e:
#             print(f"Failed to encode text '{query_text}': {e}")
#             continue
#
#         # Compute similarity for all images
#         sims = []
#         for img in all_images:
#             img_id = img['id']
#             if img_id in image_embeddings:
#                 sim = np.dot(text_vec, image_embeddings[img_id])
#                 sims.append((sim, img_id))
#             else:
#                 sims.append((-np.inf, img_id))  # image was not encoded, ignore in ranking
#
#         # Rank by similarity (descending)
#         sims.sort(reverse=True)
#         top10 = [img_id for (_, img_id) in sims[:10]]
#
#         if gt_image_id in top10:
#             hits += 1
#             print(f"Hit! Ground-truth image is in Top-10.")
#         else:
#             print(f"Miss. Ground-truth image not in Top-10.")
#         print("Top 10 IDs:", top10)
#
#     hits_at_10 = hits / n_total if n_total > 0 else 0
#     print(f"\nFinal Hits@10: {hits_at_10:.4f} ({hits} out of {n_total})")
#     return hits_at_10
#
# # ------------------------------------------
# # 3. Run the evaluation
# # ------------------------------------------
# if __name__ == "__main__":
#     evaluate_hits_at_10(test_pairs, all_images, token)
