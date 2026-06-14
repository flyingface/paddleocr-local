#!/bin/bash

set -e

echo "Deploying PaddleOCR Local..."

if [ ! -f "env.txt" ]; then
    echo "env.txt does not exist. Run build.sh or create the env file first."
    exit 1
fi

docker compose --env-file env.txt up -d --no-start
docker compose --env-file env.txt stop pandocr-web paddleocr-vl-api paddleocr-vlm-server paddleocr-ocr-api > /dev/null 2>&1 || true
docker compose --env-file env.txt start pandocr-web

echo "Waiting for services..."
sleep 5

echo ""
echo "Service status:"
docker compose --env-file env.txt ps

echo ""
echo "Health checks:"

if curl -f http://localhost:8000/ > /dev/null 2>&1; then
    echo "pandocr-web (8000) OK"
else
    echo "pandocr-web (8000) not ready"
fi

if curl -f http://localhost:8081/health > /dev/null 2>&1; then
    echo "paddleocr-vl-api (8081) OK"
else
    echo "paddleocr-vl-api (8081) standby or starting"
fi

if curl -f http://localhost:8082/health > /dev/null 2>&1; then
    echo "paddleocr-ocr-api (8082) OK"
else
    echo "paddleocr-ocr-api (8082) standby or starting"
fi

echo ""
echo "Done."
echo "WebUI: http://localhost:8000"
echo "VL API:  http://localhost:8081"
echo "OCR API: http://localhost:8082"
echo "Default model is started by pandocr-web. The other model stays stopped until selected in the UI."
echo ""
echo "Useful commands:"
echo "  docker compose --env-file env.txt logs -f"
echo "  docker compose --env-file env.txt logs -f pandocr-web"
echo "  docker compose --env-file env.txt restart pandocr-web"
echo "  docker compose --env-file env.txt down"
