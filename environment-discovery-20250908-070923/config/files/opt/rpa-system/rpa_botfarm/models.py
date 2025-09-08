# models.py - Enhanced models with validation including Evotel support
# Updated to use circuit_number for uniformity across all FNO providers
from pydantic import BaseModel, Field, field_validator
import re
from typing import Dict, Any, Optional
from datetime import datetime


class JobCreate(BaseModel):
    provider: str = Field(..., pattern="^(mfn|osn|octotel|evotel)$")  # Add evotel
    action: str = Field(..., pattern="^(validation|cancellation)$") 
    priority: int = Field(default=0, ge=0, le=10)
    parameters: Dict[str, Any]
    
    @field_validator('provider')
    @classmethod
    def validate_provider(cls, v):
        valid_providers = ["mfn", "osn", "octotel", "evotel"]  # Add evotel
        if v.lower() not in [p.lower() for p in valid_providers]:
            raise ValueError(f"Provider must be one of {valid_providers}")
        return v.lower()
    
    @field_validator('parameters')
    @classmethod
    def validate_parameters(cls, v, info):
        # Updated Evotel parameter requirements to use circuit_number
        required_fields = {
            ('mfn', 'validation'): ['circuit_number'],
            ('mfn', 'cancellation'): ['circuit_number'],
            ('osn', 'validation'): ['circuit_number'],
            ('osn', 'cancellation'): ['circuit_number', 'solution_id'],
            ('octotel', 'validation'): ['circuit_number'],
            ('octotel', 'cancellation'): ['circuit_number', 'solution_id'],
            ('evotel', 'validation'): ['circuit_number'],                    # Changed: Now uses circuit_number
            ('evotel', 'cancellation'): ['circuit_number']                  # Changed: Now uses circuit_number
        }
        
        # Get provider and action from validated data
        provider = info.data.get('provider', '').lower()
        action = info.data.get('action', '').lower()
        
        # Check required fields
        key = (provider, action)
        if key in required_fields:
            for field in required_fields[key]:
                if field not in v:
                    raise ValueError(f"Missing required field: {field}")
        
        # Sanitize all values
        sanitized = {}
        for key, value in v.items():
            sanitized[key] = sanitize_value(key, value)
        
        return sanitized
    
    @field_validator('action') 
    @classmethod
    def validate_action(cls, v):
        if v.lower() not in ['validation', 'cancellation']:
            raise ValueError("Action must be 'validation' or 'cancellation'")
        return v.lower()

def sanitize_value(key: str, value: Any) -> Any:
    """Sanitize individual values based on type and key"""
    
    # Special handling for known fields
    if key == 'circuit_number':
        # Handle circuit numbers (including those that map to Evotel serial numbers)
        if isinstance(value, str):
            # For Evotel, circuit numbers are actually serial numbers, so allow alphanumeric
            # For other providers, they might have different formats
            # Use a more permissive pattern to handle both cases
            sanitized = re.sub(r'[^a-zA-Z0-9\-]', '', value)[:50]
            # Ensure it's not empty after sanitization
            if not sanitized:
                raise ValueError("Circuit number cannot be empty after sanitization")
            return sanitized
        else:
            raise ValueError("Circuit number must be a string")
    
    elif key == 'serial_number':
        # Legacy support - in case any old code still uses serial_number
        # This should be deprecated in favor of circuit_number
        if isinstance(value, str):
            sanitized = re.sub(r'[^a-zA-Z0-9]', '', value)[:20]
            if not sanitized:
                raise ValueError("Serial number cannot be empty after sanitization")
            return sanitized
        else:
            raise ValueError("Serial number must be a string")
    
    elif key == 'solution_id':
        # Solution IDs are typically numeric
        if isinstance(value, str):
            return re.sub(r'[^0-9]', '', value)[:20]
    
    elif key == 'requested_date':
        # Validate date format
        if isinstance(value, str):
            try:
                # Expect DD/MM/YYYY format
                datetime.strptime(value, "%d/%m/%Y")
                return value
            except ValueError:
                raise ValueError(f"Invalid date format: {value}")
    
    # Generic sanitization
    if isinstance(value, str):
        # Remove dangerous characters, allow basic punctuation
        sanitized = re.sub(r'[<>"\';(){}\\]', '', value)
        # Limit length
        return sanitized[:500]
    
    elif isinstance(value, (int, float)):
        # Ensure numbers are within reasonable bounds
        if isinstance(value, int):
            return max(-999999999, min(999999999, value))
        else:
            return max(-999999999.99, min(999999999.99, value))
    
    elif isinstance(value, bool):
        return value
    
    else:
        # Convert to string and sanitize
        return re.sub(r'[<>"\';(){}\\]', '', str(value))[:500]

# Request validation for external APIs
def validate_external_request(data: Dict) -> Dict:
    """Validate external API requests"""
    
    # Check for suspicious patterns
    suspicious_patterns = [
        r'<script',
        r'javascript:',
        r'onclick=',
        r'onerror=',
        r'SELECT.*FROM',
        r'DROP.*TABLE',
        r'INSERT.*INTO',
        r'DELETE.*FROM',
        r'UNION.*SELECT',
        r'OR.*1=1',
        r'EXEC.*\(',
        r'WAITFOR.*DELAY'
    ]
    
    # Convert to string for pattern checking
    data_str = str(data).lower()
    
    for pattern in suspicious_patterns:
        if re.search(pattern, data_str, re.IGNORECASE):
            raise ValueError(f"Suspicious pattern detected: {pattern}")
    
    return data

# Evotel-specific validation helpers - Updated to use circuit_number
def validate_evotel_circuit_number(circuit_number: str) -> bool:
    """
    Validate Evotel circuit number format (which maps to their serial number format)
    Based on example: 48575443D9B290B1
    """
    if not isinstance(circuit_number, str):
        return False
    
    # Remove any whitespace
    circuit_number = circuit_number.strip()
    
    # Check length (typical Evotel serial numbers are 12-20 characters)
    if len(circuit_number) < 8 or len(circuit_number) > 20:
        return False
    
    # Check that it contains only alphanumeric characters
    if not re.match(r'^[A-Za-z0-9]+$', circuit_number):
        return False
    
    return True

def validate_evotel_parameters(parameters: Dict[str, Any], action: str) -> Dict[str, Any]:
    """
    Perform Evotel-specific parameter validation - Updated to use circuit_number
    """
    validated_params = parameters.copy()
    
    # Validate circuit number (which maps to Evotel's serial number internally)
    if 'circuit_number' in validated_params:
        circuit_number = validated_params['circuit_number']
        
        if not validate_evotel_circuit_number(circuit_number):
            raise ValueError(
                f"Invalid Evotel circuit number format: {circuit_number}. "
                "Circuit number should be 8-20 alphanumeric characters."
            )
        
        # Ensure uppercase for consistency
        validated_params['circuit_number'] = circuit_number.upper()
    
    # Legacy support for old serial_number parameter (should be deprecated)
    elif 'serial_number' in validated_params:
        # Map old serial_number to new circuit_number
        serial_number = validated_params['serial_number']
        
        if not validate_evotel_circuit_number(serial_number):
            raise ValueError(
                f"Invalid Evotel serial number format: {serial_number}. "
                "Serial number should be 8-20 alphanumeric characters."
            )
        
        # Map to circuit_number and remove serial_number
        validated_params['circuit_number'] = serial_number.upper()
        del validated_params['serial_number']
        
        # Log the mapping for tracking
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Mapped legacy serial_number '{serial_number}' to circuit_number for Evotel")
    
    # Action-specific validation
    if action == 'validation':
        # Validation only requires circuit_number
        required_fields = ['circuit_number']
    elif action == 'cancellation':
        # Cancellation requires circuit_number (and potentially other fields in the future)
        required_fields = ['circuit_number']
    else:
        raise ValueError(f"Unknown Evotel action: {action}")
    
    # Check required fields
    missing_fields = [field for field in required_fields if field not in validated_params]
    if missing_fields:
        raise ValueError(f"Missing required fields for Evotel {action}: {missing_fields}")
    
    return validated_params

# Generic circuit number validation for all providers
def validate_circuit_number_format(circuit_number: str, provider: str) -> bool:
    """
    Validate circuit number format based on provider
    """
    if not isinstance(circuit_number, str) or not circuit_number.strip():
        return False
    
    circuit_number = circuit_number.strip()
    
    # Provider-specific validation
    if provider.lower() == 'evotel':
        return validate_evotel_circuit_number(circuit_number)
    elif provider.lower() == 'mfn':
        # MFN circuit numbers are typically alphanumeric with dashes
        return bool(re.match(r'^[A-Za-z0-9\-]{5,30}$', circuit_number))
    elif provider.lower() == 'osn':
        # OSN circuit numbers are typically alphanumeric with dashes
        return bool(re.match(r'^[A-Za-z0-9\-]{5,30}$', circuit_number))
    elif provider.lower() == 'octotel':
        # Octotel circuit numbers are typically alphanumeric
        return bool(re.match(r'^[A-Za-z0-9]{5,30}$', circuit_number))
    else:
        # Generic validation for unknown providers
        return bool(re.match(r'^[A-Za-z0-9\-]{5,50}$', circuit_number))

# Backward compatibility functions
def validate_serial_number(serial_number: str) -> bool:
    """
    DEPRECATED: Use validate_circuit_number_format instead
    Kept for backward compatibility
    """
    import warnings
    warnings.warn(
        "validate_serial_number is deprecated. Use validate_circuit_number_format instead.",
        DeprecationWarning,
        stacklevel=2
    )
    return validate_evotel_circuit_number(serial_number)