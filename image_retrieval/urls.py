from django.contrib import admin
from django.urls import path
from explorer.views import home, login, callback, logout, upload_file, delete_file, proxy_image


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'),
    path('login/', login, name='login'),
    path('callback/', callback, name='callback'),
    path('logout/', logout, name='logout'),
    path('upload/', upload_file, name='upload_file'),
    path('delete/<str:file_id>/', delete_file, name='delete_file'),
    path('proxy-image/<str:item_id>/', proxy_image, name='proxy_image'),
]
