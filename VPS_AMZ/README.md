cd C:\Users\nnh16\ads-trading-system\VPS_AMZ
git add sellerboard_clone/backend/app/routers/dashboard.py sellerboard_clone/backend/app/schemas/schemas.py sellerboard_clone/backend/app/services/profit.py sellerboard_clone/frontend/app.js sellerboard_clone/frontend/index.html
git commit -m "Them dai the ky so sanh va bang hieu suat san pham chi tiet"
git push origin main
ssh sellervision@REDACTED_VPS_IP
cd ~/VPS_AMZ
git pull origin main
sudo systemctl restart sellervision
sudo systemctl status sellervision --no-pager
exit
