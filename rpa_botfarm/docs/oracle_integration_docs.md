# Oracle System Integration - Response Documentation

## Overview
This document defines the response body structure sent to the Oracle system for OSN and MFN automation reports.

## Response Structure

All responses follow this fixed JSON structure:

```json
{
  "JOB_ID": "string",
  "FNO": "string", 
  "STATUS": "string",
  "STATUS_DT": "string",
  "JOB_EVI": "string (JSON-encoded)"
}
```

### Field Definitions

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `JOB_ID` | string | External job identifier from request parameters | `"ORD_12345"` |
| `FNO` | string | Provider identifier (OSN or MFN) | `"OSN"`, `"MFN"` |
| `STATUS` | string | Business outcome status (see status values below) | `"Bitstream Validated"` |
| `STATUS_DT` | string | Timestamp in format YYYY/MM/DD HH:MM:SS | `"2025/07/02 14:30:45"` |
| `JOB_EVI` | string | JSON-encoded evidence object containing automation details | See JOB_EVI structure below |

## STATUS Values

### Validation Actions
- `"Bitstream Validated"` - Service found and active
- `"Bitstream Not Found"` - No service found for circuit
- `"Bitstream Cancellation Pending"` - Service active but has pending cancellation order
- `"Bitstream Already Cancelled"` - Service found but already deactivated
- `"Bitstream Validation Error"` - Automation failed during validation
- `"Bitstream Validation Timeout"` - Validation timed out
- `"Bitstream Validation Portal Error"` - Portal system error
- `"Bitstream Validation Auth Error"` - Authentication failure
- `"Bitstream Validation Network Error"` - Network connectivity issue
- `"Bitstream Validation System Error"` - System/driver error

### Cancellation Actions  
- `"Bitstream Delete Released"` - Cancellation successfully processed
- `"Bitstream Already Deleted"` - Service was already inactive
- `"Bitstream Not Found"` - No service found to cancel
- `"Bitstream Delete Error"` - Cancellation failed
- `"Bitstream Delete Timeout"` - Cancellation timed out
- `"Bitstream Delete Portal Error"` - Portal system error during cancellation
- `"Bitstream Delete Auth Error"` - Authentication failure during cancellation
- `"Bitstream Delete Network Error"` - Network error during cancellation
- `"Bitstream Delete System Error"` - System error during cancellation

### Error States
- `"Bitstream Processing Error"` - General processing error
- `"Bitstream Status Unknown"` - Status could not be determined

## JOB_EVI Structure

The `JOB_EVI` field contains a JSON-encoded string with automation execution details:

### Core Evidence Fields

```json
{
  "provider": "OSN|MFN",
  "action": "validation|cancellation", 
  "timestamp": "2025/07/02 14:30:45",
  "job_internal_id": "123",
  "retry_count": "0",
  "max_retries": "2",
  "execution_start": "2025-07-02T14:30:00Z",
  "execution_end": "2025-07-02T14:30:45Z",
  "assigned_worker": "worker-01",
  "automation_status": "success|failed",
  "automation_message": "Successfully extracted data for circuit FTTX123456",
  "evidence_count": "5",
  "screenshot_count": "0"
}
```

### Service Status Evidence

```json
{
  "evidence_found": "true|false",
  "evidence_is_active": "true|false", 
  "evidence_service_found": "true|false",
  "evidence_customer_found": "true|false",
  "evidence_customer_is_active": "true|false",
  "evidence_circuit_number": "FTTX123456"
}
```

### Cancellation Evidence (when applicable)

```json
{
  "evidence_cancellation_implementation_date": "2025-06-15",
  "evidence_cancellation_captured_id": "CAN789",
  "Captured_ID": "CAN789",
  "evidence_scheduled_cancellation_date": "2025-07-01"
}
```

### Order Data (OSN specific)

For OSN responses, order details are included:

```json
{
  "order_data_count": "3",
  "order_0_number": "ORD001",
  "order_0_type": "New Installation", 
  "order_0_external_ref": "EXT123",
  "order_0_service_number": "FTTX123456",
  "order_0_product_name": "Fiber 100Mbps",
  "order_0_created_on": "2024-01-15",
  "order_0_date_implemented": "2024-01-20",
  "order_0_order_status": "Implemented",
  "order_0_is_cease": "false",
  "order_0_is_pending_cease": "false", 
  "order_0_is_implemented_cease": "false"
}
```

### Count Fields

```json
{
  "evidence_total_orders": "5",
  "evidence_new_installation_count": "1",
  "evidence_cease_orders_count": "1", 
  "evidence_pending_cease_count": "0",
  "evidence_implemented_cease_count": "1"
}
```

## Provider-Specific Differences

### OSN Responses
- Include detailed order data with order_X_* fields
- Provide cease order analysis and counts
- Include pending cancellation detection
- More granular service status determination

### MFN Responses  
- Focus on customer data rather than orders
- Include customer contact details in evidence
- Simpler active/inactive status determination
- Less detailed order tracking

## Status Determination Logic

### For Both Providers:

1. **Job Failure**: If automation fails → Error status
2. **Not Found**: If no service data found → "Bitstream Not Found"
3. **Pending Cease**: If active service has pending cancellation → "Bitstream Cancellation Pending"  
4. **Active Service**: If service found and active → "Bitstream Validated"
5. **Inactive Service**: If service found but cancelled → "Bitstream Already Cancelled"

### Error Handling:
- Network issues → Network Error status
- Authentication failures → Auth Error status  
- Portal problems → Portal Error status
- Timeouts → Timeout Error status
- System errors → System Error status

## Example Complete Response

```json
{
  "JOB_ID": "ORD_12345",
  "FNO": "OSN", 
  "STATUS": "Bitstream Validated",
  "STATUS_DT": "2025/07/02 14:30:45",
  "JOB_EVI": "{\"provider\":\"OSN\",\"action\":\"validation\",\"timestamp\":\"2025/07/02 14:30:45\",\"job_internal_id\":\"123\",\"automation_status\":\"success\",\"evidence_found\":\"true\",\"evidence_is_active\":\"true\",\"evidence_circuit_number\":\"FTTX123456\",\"order_data_count\":\"2\",\"order_0_number\":\"ORD001\",\"order_0_status\":\"Implemented\"}"
}
```

## Integration Notes

- All timestamps use South African timezone
- All evidence values are converted to strings
- Empty or null values are excluded from JOB_EVI
- Response is always valid JSON structure
- HTTP 200 response expected for successful receipt