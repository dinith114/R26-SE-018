"""
Test script for Growth Stage API
"""
import requests
import json
import sys
from pathlib import Path

BASE_URL = "http://localhost:8000"

def test_health():
    """Test health endpoint"""
    print("\n🔍 Testing Health Check...")
    response = requests.get(f"{BASE_URL}/api/v1/growth/health")
    print(f"Status: {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    return response.status_code == 200

def test_stages():
    """Test stages endpoint"""
    print("\n📋 Testing Get Stages...")
    response = requests.get(f"{BASE_URL}/api/v1/growth/stages")
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Total Stages: {data.get('data', {}).get('total_stages', 0)}")
    if data.get('data', {}).get('stages'):
        print("Stage Names:", [s['stage_name'] for s in data['data']['stages']])
    return response.status_code == 200

def test_predict(image_path):
    """Test predict endpoint"""
    print(f"\n🔬 Testing Predict with {image_path}...")
    
    if not Path(image_path).exists():
        print(f"❌ Image not found: {image_path}")
        return False
    
    with open(image_path, 'rb') as f:
        files = {'file': (Path(image_path).name, f, 'image/jpeg')}
        response = requests.post(
            f"{BASE_URL}/api/v1/growth/identify",
            files=files
        )
    
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Predicted Stage: {data.get('data', {}).get('stage_label', 'Unknown')}")
        print(f"Confidence: {data.get('data', {}).get('confidence', 0):.2%}")
        print(f"Description: {data.get('data', {}).get('stage_description', '')}")
    else:
        print("Error:", response.text)
    
    return response.status_code == 200

def main():
    print("=" * 60)
    print("🌺 Orchid Growth Stage API Test")
    print("=" * 60)
    
    # Test health
    health_ok = test_health()
    
    # Test stages
    stages_ok = test_stages()
    
    # Test prediction (if image provided)
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
        predict_ok = test_predict(image_path)
    else:
        print("\n💡 To test prediction, provide image path:")
        print(f"   python test_api.py path/to/image.jpg")
    
    print("\n" + "=" * 60)
    print("✅ All tests completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()