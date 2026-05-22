$project = "chip-tracke-tw"
$sa = "687744946364-compute@developer.gserviceaccount.com"

Write-Host "授權 storage.admin..." -ForegroundColor Cyan
gcloud projects add-iam-policy-binding $project --member="serviceAccount:$sa" --role="roles/storage.admin"

Write-Host "授權 artifactregistry.admin..." -ForegroundColor Cyan
gcloud projects add-iam-policy-binding $project --member="serviceAccount:$sa" --role="roles/artifactregistry.admin"

Write-Host "開始部署..." -ForegroundColor Green
gcloud run deploy chip-tracker --source . --region asia-east1 --platform managed --allow-unauthenticated --port 8080 --memory 512Mi
