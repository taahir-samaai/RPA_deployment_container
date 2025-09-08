#!/usr/bin/env python3
"""
Direct test of Evotel validation module
"""
import sys
import os
import json

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_direct_module():
    """Test the Evotel validation module directly"""
    print("=" * 60)
    print("DIRECT MODULE TEST - Evotel Validation")
    print("=" * 60)
    
    try:
        # Import the module directly
        from automations.evotel.validation import execute
        print("✓ Module imported successfully")
        
        # Test parameters (use a test serial number)
        test_parameters = {
            "job_id": "test_direct_001",
            "serial_number": "48575443D9B290B1"  # Example from your code
        }
        
        print(f"Testing with parameters: {test_parameters}")
        print("Starting execution...")
        
        # Execute the module
        result = execute(test_parameters)
        
        print("\n" + "=" * 40)
        print("EXECUTION RESULT:")
        print("=" * 40)
        print(json.dumps(result, indent=2, default=str))
        
        # Validate result structure
        assert isinstance(result, dict), "Result must be a dictionary"
        assert "status" in result, "Result must contain 'status' field"
        
        if result.get("status") == "success":
            print("\n✓ Module executed successfully!")
            
            # Check for expected fields
            details = result.get("details", {})
            if details.get("found"):
                print("✓ Service found in Evotel portal")
                
                # Print service summary if available
                service_summary = details.get("service_summary", {})
                if service_summary:
                    print("\nService Summary:")
                    for key, value in service_summary.items():
                        if value:
                            print(f"  {key}: {value}")
            else:
                print("- Service not found in Evotel portal")
                
        else:
            print(f"\n⚠ Module execution completed with status: {result.get('status')}")
            if result.get("message"):
                print(f"Message: {result['message']}")
                
        return True
        
    except ImportError as e:
        print(f"✗ Failed to import module: {e}")
        print("\nCheck that:")
        print("1. The file is renamed to validation.py")
        print("2. It's in automations/evotel/ directory")
        print("3. __init__.py files exist in automations/ and automations/evotel/")
        return False
        
    except Exception as e:
        print(f"✗ Module execution failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_direct_module()
    sys.exit(0 if success else 1)