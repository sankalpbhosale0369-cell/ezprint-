import cloudinary
import cloudinary.uploader
import cloudinary.api

cloudinary.config(
    cloud_name = "dlimcfiru",
    api_key = "695264972578198",
    api_secret = "ZvIrX1k3X52wHFMykmDaSaMolWw"
)

result = cloudinary.uploader.upload(
    r"C:\Users\Asus\Desktop\Test.pdf",   # koi bhi small file (pdf / image)
    resource_type="raw"
)

print("Uploaded URL:", result["secure_url"])
