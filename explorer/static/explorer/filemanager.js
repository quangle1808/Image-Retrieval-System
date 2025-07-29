document.addEventListener("DOMContentLoaded", function() {
  const uploadInput = document.querySelector(".upload-form input[type='file']");
  const previewImg = document.getElementById("upload-preview");

  // Extension to icon mapping (should match your static/explorer assets)
  const ICONS = {
    'pdf': '',
    'doc': '',
    'docx': '',
    'jpg': '', // use real preview
    'jpeg': '',
    'png': '',
    'gif': '',
    'bmp': '',
    'webp': '',
    'default': "/static/explorer/file-icon.png"
  };

  if (uploadInput && previewImg) {
    uploadInput.addEventListener("change", function(e) {
      const file = e.target.files[0];
      if (!file) {
        previewImg.src = "";
        previewImg.style.display = "none";
        return;
      }

      const ext = file.name.split('.').pop().toLowerCase();
      const isImage = file.type.startsWith("image/");
      const isPDF = ext === "pdf";
      const isDoc = ext === "doc" || ext === "docx";

      if (isImage) {
        const reader = new FileReader();
        reader.onload = function(evt) {
          previewImg.src = evt.target.result;
          previewImg.style.display = "inline-block";
        }
        reader.readAsDataURL(file);
      } else if (isPDF) {
        previewImg.src = ICONS['pdf'];
        previewImg.style.display = "inline-block";
      } else if (isDoc) {
        previewImg.src = ICONS['doc'];
        previewImg.style.display = "inline-block";
      } else {
        previewImg.src = ICONS['default'];
        previewImg.style.display = "inline-block";
      }

      // Auto-upload after 200ms for all files
      setTimeout(function() {
        document.getElementById('uploadForm').submit();
      }, 200);
    });
  }

  // Custom confirm for delete
  document.querySelectorAll(".delete-form button").forEach(btn => {
    btn.addEventListener("click", function(e) {
      e.preventDefault();
      const ok = window.confirm("Are you sure you want to delete this file?");
      if (ok) {
        btn.closest("form").submit();
      }
    });
  });
});
