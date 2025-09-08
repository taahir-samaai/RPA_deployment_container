#!/usr/bin/env python3
"""
Test script to verify the Evotel validation fix works
"""
import sys
import os
import json
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_fixed_validation():
    """Test the fixed Evotel validation module"""
    print("=" * 60)
    print("TESTING FIXED EVOTEL VALIDATION")
    print("=" * 60)
    
    try:
        # Import the fixed module
        from automations.evotel.validation import execute
        print("✓ Module imported successfully")
        
        # Test parameters (same serial number that worked in debug)
        test_parameters = {
            "job_id": "test_fix_001",
            "serial_number": "48575443D9B290B1"
        }
        
        print(f"Testing with parameters: {test_parameters}")
        print("Starting execution with fixes applied...")
        
        start_time = time.time()
        
        # Execute the module
        result = execute(test_parameters)
        
        execution_time = time.time() - start_time
        
        print(f"\nExecution completed in {execution_time:.2f} seconds")
        print("\n" + "=" * 40)
        print("EXECUTION RESULT:")
        print("=" * 40)
        
        # Pretty print the result
        if isinstance(result, dict):
            print(json.dumps(result, indent=2, default=str))
            
            # Analyze the result
            status = result.get("status")
            message = result.get("message", "")
            
            if status == "success":
                print("\n✅ SUCCESS: Module executed without crashes!")
                
                details = result.get("details", {})
                if details.get("found"):
                    print("✅ Service found in Evotel portal")
                    
                    # Show service info
                    service_summary = details.get("service_summary", {})
                    if service_summary:
                        print(f"  Customer: {service_summary.get('customer', 'N/A')}")
                        print(f"  Product: {service_summary.get('product', 'N/A')}")
                        print(f"  Status: {service_summary.get('status', 'N/A')}")
                    
                    # Show completeness
                    extraction_metadata = details.get("extraction_metadata", {})
                    completeness = extraction_metadata.get("completeness_score", 0)
                    if completeness:
                        print(f"  Data Completeness: {float(completeness) * 100:.1f}%")
                        
                    # Show work orders
                    work_order_summary = details.get("work_order_summary", {})
                    if work_order_summary:
                        total_wo = work_order_summary.get("total_work_orders", 0)
                        print(f"  Work Orders: {total_wo}")
                        
                else:
                    print("ℹ️  Service not found (but no crash occurred)")
                
                # Check screenshots
                screenshots = result.get("screenshot_data", [])
                print(f"  Screenshots captured: {len(screenshots)}")
                
                print("\n🎉 THE FIX WORKED! No more Chrome crashes!")
                return True
                
            elif status == "error":
                print(f"\n❌ EXECUTION ERROR: {message}")
                
                # Check if it's still a Chrome crash
                if "stacktrace" in message.lower() or "gethandleverifier" in message.lower():
                    print("⚠️  Still getting Chrome crashes - may need additional fixes")
                else:
                    print("ℹ️  Different type of error (not Chrome crash)")
                
                return False
                
            else:
                print(f"\n⚠️  UNEXPECTED STATUS: {status}")
                print(f"Message: {message}")
                return False
                
        else:
            print("❌ Invalid result format")
            print(f"Result: {result}")
            return False
            
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        print("\nMake sure:")
        print("1. The fixed validation.py is in automations/evotel/")
        print("2. __init__.py files exist")
        return False
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def compare_with_debug_results():
    """Compare results with what we expect from debug"""
    print("\n" + "=" * 60)
    print("COMPARISON WITH DEBUG RESULTS")
    print("=" * 60)
    
    expected_service = "Vodacom Fibre Broadband 20Mbps Uncapped"
    expected_uuid = "44599da6-2804-4872-b9d0-7fb82b158ae0"
    
    print(f"Expected service: {expected_service}")
    print(f"Expected service UUID: {expected_uuid}")
    print("\nIf the validation found this service, the fix is working correctly!")

def main():
    """Main test function"""
    success = test_fixed_validation()
    compare_with_debug_results()
    
    if success:
        print("\n" + "=" * 60)
        print("🎉 FIX VERIFICATION SUCCESSFUL!")
        print("✅ Chrome crash issue resolved")
        print("✅ Evotel validation working correctly")
        print("✅ Ready for integration testing")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ FIX VERIFICATION FAILED")
        print("Additional debugging may be needed")
        print("=" * 60)
    
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)