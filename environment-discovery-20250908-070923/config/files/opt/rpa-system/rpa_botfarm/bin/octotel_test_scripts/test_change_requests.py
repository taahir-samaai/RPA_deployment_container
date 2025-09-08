"""
Simple test script - save this as test_change_requests.py
"""

from datetime import datetime

def test_enhanced_validation(circuit_number="VOD66900"):
    """
    Test the enhanced validation with change request extraction
    """
    
    try:
        from automations.octotel.validation import execute
        
        print(f"Testing enhanced validation for {circuit_number}...")
        print("="*60)
        
        # Execute validation with change request extraction
        result = execute({
            "job_id": f"TEST_CR_EXTRACTION_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "circuit_number": circuit_number
        })
        
        print("=== VALIDATION STATUS ===")
        print(f"Status: {result.get('status')}")
        print(f"Message: {result.get('message')}")
        print(f"Found: {result.get('details', {}).get('found', False)}")
        
        if result.get('details') and result['details'].get('services'):
            service = result['details']['services'][0]
            
            print("\n=== SERVICE INFORMATION ===")
            print(f"Circuit: {service['service_identifiers']['primary_id']}")
            print(f"Customer: {service['customer_information'].get('name', 'N/A')}")
            print(f"Status: {service['status_information'].get('current_status', 'N/A')}")
            
            # NEW: Change Request Information
            change_requests = service.get('change_requests', {})
            
            print("\n=== CHANGE REQUEST EXTRACTION ===")
            print(f"Change requests found: {change_requests.get('change_requests_found', False)}")
            print(f"Total change requests: {change_requests.get('total_change_requests', 0)}")
            print(f"Extraction successful: {change_requests.get('extraction_successful', False)}")
            
            if change_requests.get('change_requests_found'):
                print(f"Table headers: {change_requests.get('table_headers', [])}")
                
                # First change request details
                first_cr = change_requests.get('first_change_request', {})
                if first_cr:
                    print(f"\n--- FIRST CHANGE REQUEST ---")
                    print(f"ID: {first_cr.get('id', 'Not found')}")
                    print(f"Type: {first_cr.get('type', 'Not found')}")
                    print(f"Status: {first_cr.get('status', 'Not found')}")
                    print(f"Due Date: {first_cr.get('due_date', 'Not found')}")
                    print(f"Requested By: {first_cr.get('requested_by', 'Not found')}")
                    print(f"Full Row: {first_cr.get('full_row_text', 'Not found')}")
                
                # Raw table data for debugging
                print(f"\n--- RAW TABLE DATA ---")
                print(f"Raw table text (first 200 chars):")
                raw_text = change_requests.get('raw_table_text', '')
                print(f"{raw_text[:200]}{'...' if len(raw_text) > 200 else ''}")
                
            else:
                print("❌ No change requests table found")
                print("This might indicate:")
                print("- No change requests exist for this service")
                print("- Table structure doesn't match expected selectors")
                print("- Service details page didn't load properly")
            
        else:
            print("❌ No service data found")
        
        return result
        
    except Exception as e:
        print(f"❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    print("Enhanced Octotel Validation - Change Request Extraction Test")
    print("="*70)
    
    # Test the circuit from your logs
    test_enhanced_validation("VOD66900")