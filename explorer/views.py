from django.shortcuts import render, redirect
from django.core.paginator import Paginator
from django.conf import settings
from msal import ConfidentialClientApplication
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponseRedirect, HttpResponse
from django.urls import reverse
import requests, uuid, numpy as np, pickle, os, time
import torch
from PIL import Image

from .clip_model import encode_text, encode_image_from_url, model, preprocess, device

# --------- New Helper to Get User ID ---------
def get_user_id(request):
    token = request.session.get('access_token')
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get("https://graph.microsoft.com/v1.0/me", headers=headers)
    if resp.status_code == 200:
        return resp.json().get("id", "default")
    return "default"

# --------- The Sync Function ---------
def sync_onedrive_images(request):
    token = request.session.get('access_token')
    user_id = get_user_id(request)
    user_dir = os.path.join("/tmp/onedrive_cache", str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    embedding_path = os.path.join(user_dir, "clip_embeddings.pkl")
    mapping_path = os.path.join(user_dir, "file_id_to_name.pkl")

    # MSAL app instance for token refresh
    msal_app = ConfidentialClientApplication(
        settings.MICROSOFT_CLIENT_ID,
        authority=settings.MICROSOFT_AUTHORITY,
        client_credential=settings.MICROSOFT_CLIENT_SECRET,
    )

    # Load or initialize embedding cache and ID-name mapping
    if os.path.exists(embedding_path):
        with open(embedding_path, "rb") as f:
            embedding_cache = pickle.load(f)
    else:
        embedding_cache = {}

    if os.path.exists(mapping_path):
        with open(mapping_path, "rb") as f:
            file_id_to_name = pickle.load(f)
    else:
        file_id_to_name = {}

    images = recursive_onedrive_images(token)
    current_ids = set(item["id"] for item in images)
    id_name_new = {item["id"]: item["name"] for item in images}

    # --- Remove deleted files and embeddings ---
    files_on_disk = set(os.listdir(user_dir))
    for file_id, fname in list(file_id_to_name.items()):
        if file_id not in current_ids:
            # Remove local file if present
            path = os.path.join(user_dir, fname)
            if os.path.exists(path):
                try:
                    os.remove(path)
                    print(f"Deleted local file no longer in OneDrive: {fname}")
                except Exception as e:
                    print(f"Error deleting {fname}: {e}")
            # Remove mapping and embedding
            embedding_cache.pop(file_id, None)
            del file_id_to_name[file_id]
            print(f"Removed stale embedding/mapping for {file_id}")

    new_files = 0
    for item in images:
        file_id = item["id"]
        file_name = item["name"]
        ext = os.path.splitext(file_name)[1].lower()
        if ext not in [".jpg", ".jpeg", ".png"]:
            continue
        local_path = os.path.join(user_dir, file_name)  # Save with original file name
        file_id_to_name[file_id] = file_name  # Update mapping
        if not os.path.exists(local_path):
            content = download_onedrive_file(file_id, token, msal_app, request)
            if content:
                with open(local_path, "wb") as f:
                    f.write(content)
                print(f"Downloaded: {file_name}")
            else:
                print(f"Failed to download: {file_name}")
                continue
        if file_id not in embedding_cache:
            try:
                img = preprocess(Image.open(local_path)).unsqueeze(0).to(device)
                with torch.no_grad():
                    embedding = model.encode_image(img).cpu().numpy()
                embedding_cache[file_id] = embedding
                new_files += 1
                print(f"Embedded: {file_name}")
            except Exception as e:
                print(f"Error embedding {file_name}: {e}")

    # Save caches/mapping
    with open(embedding_path, "wb") as f:
        pickle.dump(embedding_cache, f)
    with open(mapping_path, "wb") as f:
        pickle.dump(file_id_to_name, f)
    print(f"Synced {new_files} new images and updated {len(file_id_to_name)} mappings for user {user_id}.")

    return embedding_cache, user_dir, file_id_to_name


# ------------- Django Auth Views ---------------
def login(request):
    request.session["state"] = str(uuid.uuid4())
    app = ConfidentialClientApplication(
        settings.MICROSOFT_CLIENT_ID,
        authority=settings.MICROSOFT_AUTHORITY,
        client_credential=settings.MICROSOFT_CLIENT_SECRET,
    )
    auth_url = app.get_authorization_request_url(
        scopes=settings.MICROSOFT_SCOPE,
        state=request.session["state"],
        redirect_uri=settings.MICROSOFT_REDIRECT_URI
    )
    return redirect(auth_url)

def callback(request):
    if request.GET.get('state') != request.session.get("state"):
        return redirect("/")
    code = request.GET.get("code")
    app = ConfidentialClientApplication(
        settings.MICROSOFT_CLIENT_ID,
        authority=settings.MICROSOFT_AUTHORITY,
        client_credential=settings.MICROSOFT_CLIENT_SECRET,
    )
    result = app.acquire_token_by_authorization_code(
        code,
        scopes=settings.MICROSOFT_SCOPE,
        redirect_uri=settings.MICROSOFT_REDIRECT_URI
    )
    if "access_token" in result:
        request.session["access_token"] = result["access_token"]
        # Call sync after login
        sync_onedrive_images(request)
        return redirect("/")
    else:
        return render(request, "explorer/error.html", {"error": result.get("error_description")})

def logout(request):
    request.session.flush()
    return redirect("https://login.microsoftonline.com/common/oauth2/v2.0/logout?post_logout_redirect_uri=http://localhost:8000/")

def home(request):
    import mimetypes

    # Debug: Print device information for CLIP model
    if torch.cuda.is_available():
        print("CLIP Model is running on GPU:", torch.cuda.get_device_name(0))
    else:
        print("CLIP Model is running on CPU")

    token = request.session.get("access_token")
    if not token:
        return redirect("login")

    # Validate token
    headers = {"Authorization": f"Bearer {token}"}
    check = requests.get("https://graph.microsoft.com/v1.0/me", headers=headers)
    if check.status_code == 401:
        request.session.flush()
        return redirect("login")

    query = request.GET.get("query", "").strip()
    page = request.GET.get("page", 1)
    folder_id = request.GET.get("folder", "root")

    # Get filter parameter from GET, default to 'All'
    filter_type = request.GET.get("filter", "All")

    # Paths for embedding and mapping
    user_id = get_user_id(request)
    user_dir = os.path.join("/tmp/onedrive_cache", str(user_id))
    embedding_path = os.path.join(user_dir, "clip_embeddings.pkl")
    mapping_path = os.path.join(user_dir, "file_id_to_name.pkl")

    # Load caches
    if os.path.exists(embedding_path):
        with open(embedding_path, "rb") as f:
            embedding_cache = pickle.load(f)
    else:
        embedding_cache = {}

    if os.path.exists(mapping_path):
        with open(mapping_path, "rb") as f:
            file_id_to_name = pickle.load(f)
    else:
        file_id_to_name = {}

    # Map filter_type to allowed file extensions
    FILTER_MAP = {
        "All": None,
        "Document": (".pdf", ".doc", ".docx", ".txt", ".ppt", ".pptx", ".xls", ".xlsx"),
        "Image": (".jpg", ".jpeg", ".png", ".bmp", ".gif"),
        "Audio": (".mp3", ".wav", ".aac", ".ogg", ".m4a"),
        "Video": (".mp4", ".avi", ".mov", ".mkv", ".flv"),
    }

    def passes_filter(filename):
        if filter_type == "All":
            return True
        exts = FILTER_MAP.get(filter_type)
        if not exts:
            return True
        return filename.lower().endswith(exts)

    # ----------- MAIN SEARCH BRANCH -----------
    if query:
        overall_start_time = time.time()
        prev_query = request.session.get("last_query", None)
        prev_results = request.session.get("last_results", None)
        prev_filter = request.session.get("last_filter", None)

        # Only use cache if both query and filter match last search
        if prev_query == query and prev_results and prev_filter == filter_type:
            sorted_images = prev_results
            print("Using cached search results for:", query, "with filter:", filter_type)
        else:
            print(f"Search query: {query} | Filter: {filter_type}")

            # Load candidate items (filtered)
            items = []
            for fid, fname in file_id_to_name.items():
                if passes_filter(fname) and fid in embedding_cache:
                    items.append({
                        "id": fid,
                        "name": fname,
                    })
            print("Cached local items found (after filter):", len(items))

            filename_matches = []
            semantic_matches = []
            matched_ids = set()

            query_lower = query.lower()

            # ---- Filename Matches ----
            for item in items:
                if query_lower in item["name"].lower():
                    img_url = reverse('proxy_image', args=[item["id"]])
                    filename_matches.append((item["name"], img_url, 1.0, None))
                    matched_ids.add(item["id"])

            # ---- Semantic Matches ----
            text_features = encode_text(query).numpy()
            text_norm = text_features / np.linalg.norm(text_features)
            for item in items:
                if item["id"] in matched_ids:
                    continue
                image_vector = embedding_cache[item["id"]]
                image_norm = image_vector / np.linalg.norm(image_vector)
                score = float(np.dot(text_norm, image_norm.T))
                img_url = reverse('proxy_image', args=[item["id"]])
                semantic_matches.append((item["name"], img_url, score, None))

            print("Filename matches:", len(filename_matches), "Semantic matches:", len(semantic_matches))
            semantic_matches.sort(key=lambda x: -x[2])
            filename_matches.sort(key=lambda x: x[0].lower())

            sorted_images = filename_matches + semantic_matches
            request.session["last_query"] = query
            request.session["last_results"] = sorted_images
            request.session["last_filter"] = filter_type

        overall_end_time = time.time()
        print("Complete time for retrieval (all steps): {:.2f} seconds".format(overall_end_time - overall_start_time))

        paginator = Paginator(sorted_images, 20)  # 20 per page
        page_obj = paginator.get_page(page)
        return render(request, "explorer/index.html", {
            "images": page_obj.object_list,
            "page_obj": page_obj,
            "query": query,
            "filter_type": filter_type,
        })

    # ----------- BROWSE FOLDER BRANCH -----------
    else:
        all_items, parent_id = list_onedrive_items(token, folder_id)
        # Filter files in folder view (skip for folders)
        filtered_items = []
        for item in all_items:
            if item['type'] == 'folder' or passes_filter(item['name']):
                filtered_items.append(item)
        paginator = Paginator(filtered_items, 20)
        page_obj = paginator.get_page(page)
        return render(request, "explorer/index.html", {
            "items": page_obj.object_list,
            "page_obj": page_obj,
            "folder_id": folder_id,
            "parent_id": parent_id,
            "filter_type": filter_type,
        })

# Keep your utility functions as they are...
def list_onedrive_items(token, folder_id='root'):
    # ... (same as your code)
    url = f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}/children?$expand=thumbnails"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code == 401:
        return None, None
    data = resp.json().get("value", [])
    results = []
    for item in data:
        thumbnails = item.get("thumbnails", [])
        thumbnail_url = None
        if thumbnails and "medium" in thumbnails[0]:
            thumbnail_url = thumbnails[0]["medium"].get("url")
        results.append({
            "id": item["id"],
            "name": item["name"],
            "type": "folder" if "folder" in item else "file",
            "thumbnail": thumbnail_url
        })
    parent_id = None
    if folder_id != "root":
        folder_url = f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}"
        folder_resp = requests.get(folder_url, headers=headers)
        if folder_resp.status_code == 200:
            parent_ref = folder_resp.json().get("parentReference", {})
            parent_id = parent_ref.get("id", "root") if parent_ref else "root"
    return results, parent_id

def recursive_onedrive_images(token, folder_id='root'):
    """
    Recursively find all images in all folders on OneDrive (no limit).
    """
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}/children?$top=200"
    images = []

    while url:
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            print(f"Error fetching folder {folder_id}: {resp.status_code}")
            return images
        data = resp.json()
        files = data.get("value", [])
        for f in files:
            name = f.get("name", "")
            if 'folder' in f:
                # Recursively get images in subfolders
                images.extend(recursive_onedrive_images(token, folder_id=f['id']))
            elif name.lower().endswith(('.jpg', '.jpeg', '.png')):
                images.append({
                    "name": name,
                    "id": f.get("id"),
                })
        url = data.get("@odata.nextLink", None)  # This will page until all files are fetched

    return images


def get_thumbnail_url(token, file_id):
    url = f"https://graph.microsoft.com/v1.0/me/drive/items/{file_id}/thumbnails"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        thumbs = resp.json().get("value", [])
        if thumbs and "medium" in thumbs[0]:
            return thumbs[0]["medium"]["url"]
        elif thumbs and "small" in thumbs[0]:
            return thumbs[0]["small"]["url"]
    return None

@csrf_exempt
def upload_file(request):
    if request.method == "POST" and request.FILES.get('file'):
        token = request.session.get("access_token")
        if not token:
            return redirect("login")
        folder_id = request.POST.get("folder_id", "root")
        uploaded_file = request.FILES['file']
        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}:/"+uploaded_file.name+":/content"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream"
        }
        resp = requests.put(url, headers=headers, data=uploaded_file.read())
        if resp.status_code in [200, 201]:
            # After upload, re-sync!
            sync_onedrive_images(request)
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))
        else:
            return render(request, "explorer/error.html", {"error": f"Upload failed: {resp.status_code} {resp.text}"})
    else:
        return redirect("home")

@csrf_exempt
def delete_file(request, file_id):
    if request.method == "POST":
        token = request.session.get("access_token")
        if not token:
            return redirect("login")
        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{file_id}"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        resp = requests.delete(url, headers=headers)
        if resp.status_code in [204, 200]:
            # After delete, re-sync!
            sync_onedrive_images(request)
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))
        else:
            return render(request, "explorer/error.html", {"error": f"Delete failed: {resp.status_code} {resp.text}"})
    else:
        return redirect("home")

def proxy_image(request, item_id):
    # Serve local file if available, else fallback to OneDrive
    user_id = get_user_id(request)
    user_dir = os.path.join("/tmp/onedrive_cache", str(user_id))
    for ext in ['.jpg', '.jpeg', '.png']:
        local_path = os.path.join(user_dir, item_id + ext)
        if os.path.exists(local_path):
            with open(local_path, "rb") as f:
                return HttpResponse(f.read(), content_type="image/jpeg")
    # Fallback to OneDrive API (if not yet synced)
    access_token = request.session.get('access_token')
    if not access_token:
        return HttpResponse("Unauthorized", status=401)
    url = f"https://graph.microsoft.com/v1.0/me/drive/items/{item_id}/content"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(url, headers=headers, stream=True)
    if resp.status_code != 200:
        return HttpResponse("Failed to fetch image.", status=resp.status_code)
    content_type = resp.headers.get('Content-Type', 'image/jpeg')
    return HttpResponse(resp.content, content_type=content_type)



def download_onedrive_file(file_id, token, msal_app, request, max_retries=2):
    """
    Download a file from OneDrive, handling token expiration and auto-refresh.
    Updates session access_token if refreshed.
    """
    url = f"https://graph.microsoft.com/v1.0/me/drive/items/{file_id}/content"
    headers = {"Authorization": f"Bearer {token}"}
    for attempt in range(max_retries):
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            return resp.content
        elif resp.status_code == 401:
            print("Access token expired, attempting refresh...")
            # Attempt to refresh token
            result = msal_app.acquire_token_silent(settings.MICROSOFT_SCOPE, account=None)
            if result and "access_token" in result:
                token = result["access_token"]
                request.session["access_token"] = token
                headers["Authorization"] = f"Bearer {token}"
                continue
            else:
                print("Failed to refresh token. User must login again.")
                break
        else:
            print(f"Failed to fetch image {file_id}, status: {resp.status_code}")
            break
    return None