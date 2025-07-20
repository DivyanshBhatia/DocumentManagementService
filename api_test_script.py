# test_api.py
import requests
import json
from datetime import date, timedelta

# API Base URL
BASE_URL = "http://localhost:8000"

def get_token(username="admin", role="admin"):
    """Get JWT token for authentication"""
    response = requests.post(f"{BASE_URL}/auth/token", params={
        "username": username,
        "role": role
    })
    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        print(f"Failed to get token: {response.text}")
        return None

def test_create_document(token):
    """Test creating a new document"""
    headers = {"Authorization": f"Bearer {token}"}
    
    document_data = {
        "document_type": "Test License",
        "document_owner": "Test Owner",
        "document_number": f"TEST-{date.today().strftime('%Y%m%d')}",
        "expiry_date": (date.today() + timedelta(days=60)).isoformat(),
        "action_due_date": (date.today() + timedelta(days=45)).isoformat()
    }
    
    response = requests.post(
        f"{BASE_URL}/documents/",
        headers=headers,
        json=document_data
    )
    
    print(f"Create Document Status: {response.status_code}")
    if response.status_code == 200:
        print(f"Created Document: {response.json()}")
        return response.json()["sno"]
    else:
        print(f"Error: {response.text}")
        return None

def test_get_documents(token):
    """Test retrieving all documents"""
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(f"{BASE_URL}/documents/", headers=headers)
    
    print(f"Get Documents Status: {response.status_code}")
    if response.status_code == 200:
        documents = response.json()
        print(f"Total Documents: {len(documents)}")
        for doc in documents[:3]:  # Show first 3
            print(f"- {doc['document_type']}: {doc['document_number']}")
    else:
        print(f"Error: {response.text}")

def test_get_single_document(token, sno):
    """Test retrieving a single document"""
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(f"{BASE_URL}/documents/{sno}", headers=headers)
    
    print(f"Get Single Document Status: {response.status_code}")
    if response.status_code == 200:
        print(f"Document: {response.json()}")
    else:
        print(f"Error: {response.text}")

def test_update_document(token, sno):
    """Test updating a document"""
    headers = {"Authorization": f"Bearer {token}"}
    
    update_data = {
        "document_type": "Updated Test License",
        "expiry_date": (date.today() + timedelta(days=90)).isoformat()
    }
    
    response = requests.put(
        f"{BASE_URL}/documents/{sno}",
        headers=headers,
        json=update_data
    )
    
    print(f"Update Document Status: {response.status_code}")
    if response.status_code == 200:
        print(f"Updated Document: {response.json()}")
    else:
        print(f"Error: {response.text}")

def test_expiring_documents(token):
    """Test getting expiring documents"""
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(
        f"{BASE_URL}/documents/expiring/soon?days=90",
        headers=headers
    )
    
    print(f"Expiring Documents Status: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print(f"Documents expiring in 90 days: {result['count']}")
    else:
        print(f"Error: {response.text}")

def test_manual_reminder(token):
    """Test manual reminder check"""
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.post(f"{BASE_URL}/reminder/check", headers=headers)
    
    print(f"Manual Reminder Status: {response.status_code}")
    if response.status_code == 200:
        print(f"Reminder Response: {response.json()}")
    else:
        print(f"Error: {response.text}")

def test_health_check():
    """Test health check endpoint"""
    response = requests.get(f"{BASE_URL}/health")
    
    print(f"Health Check Status: {response.status_code}")
    if response.status_code == 200:
        print(f"Health Status: {response.json()}")
    else:
        print(f"Error: {response.text}")

def main():
    print("Testing Document Management API")
    print("=" * 40)
    
    # Test health check (no auth required)
    print("\n1. Testing Health Check:")
    test_health_check()
    
    # Get authentication token
    print("\n2. Getting Authentication Token:")
    token = get_token()
    if not token:
        print("Failed to get token. Exiting.")
        return
    print(f"Token obtained successfully: {token[:50]}...")
    
    # Test CRUD operations
    print("\n3. Testing Create Document:")
    document_sno = test_create_document(token)
    
    print("\n4. Testing Get All Documents:")
    test_get_documents(token)
    
    if document_sno:
        print(f"\n5. Testing Get Single Document (SNO: {document_sno}):")
        test_get_single_document(token, document_sno)
        
        print(f"\n6. Testing Update Document (SNO: {document_sno}):")
        test_update_document(token, document_sno)
    
    print("\n7. Testing Expiring Documents:")
    test_expiring_documents(token)
    
    print("\n8. Testing Manual Reminder:")
    test_manual_reminder(token)
    
    print("\n" + "=" * 40)
    print("API Testing Complete!")

if __name__ == "__main__":
    main()