# Oracle Schema - Static Base Fields + Dynamic JOB_EVI

## **STATIC BASE PAYLOAD** (Always Same Structure)

These 5 fields are **always present and predictable** - use these for your table columns:

```sql
CREATE TABLE rpa_job_status (
    id              NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    
    -- STATIC BASE FIELDS (always present, predictable)
    job_id          VARCHAR2(100) NOT NULL,    -- From JOB_ID
    fno             VARCHAR2(20) NOT NULL,     -- From FNO  
    status          VARCHAR2(100) NOT NULL,    -- From STATUS
    status_dt       VARCHAR2(20) NOT NULL,     -- From STATUS_DT
    job_evi         CLOB NOT NULL,             -- From JOB_EVI (dynamic content)
    
    -- SYSTEM FIELDS
    received_dt     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed       CHAR(1) DEFAULT 'N'
);
```

### **Base Payload Structure (Never Changes)**
```json
{
  "JOB_ID": "string(100)",     // External job identifier
  "FNO": "string(20)",         // Provider: MFN|OSN|OCTOTEL  
  "STATUS": "string(100)",     // Business status (see status list below)
  "STATUS_DT": "string(20)",   // Format: YYYY/MM/DD HH:MM:SS
  "JOB_EVI": "clob"           // JSON string (DYNAMIC CONTENT)
}
```

## **DYNAMIC JOB_EVI CONTENT** (Inside the CLOB)

The `JOB_EVI` field contains a JSON string with **3 possible structures**:

### **Core Fields** (Always in JOB_EVI)
```json
{
  "provider": "MFN|OSN|OCTOTEL",
  "action": "validation|cancellation", 
  "timestamp": "YYYY/MM/DD HH:MM:SS",
  "job_internal_id": "string",
  "retry_count": "string",
  "max_retries": "string"
}
```

### **Scenario 1: Error Cases** (Core + Error Fields)
```json
{
  // Core fields +
  "error_occurred": "true",
  "error_message": "string(4000)",
  "error_type": "TIMEOUT_ERROR|WEBDRIVER_ERROR|LOGIN_ERROR|PORTAL_UNRESPONSIVE|NETWORK_ERROR|AUTOMATION_ERROR",
  "failed_at_step": "automation_execution"
}
```

### **Scenario 2: Not Found Cases** (Core + Search Fields)
```json
{
  // Core fields +
  "search_attempted": "true",
  "search_result": "no_results_found",
  "circuit_number": "string", 
  "not_found_message": "string",
  "operation_successful": "true",
  "found_service": "false"
}
```

### **Scenario 3: Success Cases** (Core + Evidence Fields)
```json
{
  // Core fields +
  "Captured_ID": "string",              // Optional cancellation ID
  "evidence_found": "true",
  "evidence_is_active": "true|false",
  "evidence_service_found": "true",
  "evidence_customer_found": "true",
  // ... 50+ more evidence_ fields
}
```

---

## **OSN VALIDATION DATA DOCUMENTATION**

### **OSN Success Response - JOB_EVI Content**

#### **Core OSN Fields** (Always Present)
```json
{
  "provider": "OSN",
  "action": "validation",
  "timestamp": "2025/06/26 14:30:45",
  "job_internal_id": "123",
  "retry_count": "0", 
  "max_retries": "3"
}
```

#### **OSN Customer Evidence Fields**
```json
{
  "evidence_found": "true",
  "evidence_customer_found": "true",
  "evidence_customer_name": "JOHN",
  "evidence_customer_surname": "DOE", 
  "evidence_customer_email": "john.doe@example.com",
  "evidence_customer_mobile": "0821234567",
  "evidence_customer_address": "123 Main Street, Cape Town, 8001",
  "evidence_customer_circuit_number": "B310155685"
}
```

#### **OSN Service Status Fields**
```json
{
  "evidence_service_found": "true",
  "evidence_is_active": "true|false",
  "evidence_customer_is_active": "true|false", 
  "evidence_validation_status": "Bitstream Validated|Bitstream Already Cancelled|Bitstream Cancellation Pending",
  "evidence_service_status": "active|cancelled|cancellation_pending",
  "evidence_requires_cancellation": "true|false"
}
```

#### **OSN Order Analysis Fields**
```json
{
  "evidence_total_orders": "5",
  "evidence_new_installation_count": "1",
  "evidence_cease_orders_count": "1",
  
  // If cease order exists
  "evidence_cease_implementation_date": "2025-01-15",
  "evidence_cease_created_date": "2025-01-10", 
  "evidence_cease_external_ref": "REF123",
  "evidence_cease_order_status": "Implemented",
  "evidence_pending_cease_order": "false",
  "evidence_primary_requested_cease_date": "2025-01-15"
}
```

#### **OSN Cancellation Fields** (If Found)
```json
{
  "Captured_ID": "ORD123456789",                    // Cease order number
  "evidence_cease_implementation_date": "2025-01-15",
  "evidence_primary_circuit_number": "B310155685"
}
```

### **OSN STATUS Field Values** (In Base Payload)

#### **Validation Statuses**
- `"Bitstream Validated"` - Active service found
- `"Bitstream Already Cancelled"` - Service deactivated 
- `"Bitstream Cancellation Pending"` - Cease order submitted but not implemented
- `"Bitstream Not Found"` - Circuit doesn't exist
- `"Bitstream Validation Error"` - Technical failure

#### **Cancellation Statuses**  
- `"Bitstream Delete Released"` - Cancellation successful
- `"Bitstream Already Deleted"` - Already cancelled
- `"Bitstream Delete Error"` - Technical failure

### **Sample OSN Payloads**

#### **1. OSN Active Service**
```json
{
  "JOB_ID": "OSN_VAL_001",
  "FNO": "OSN",
  "STATUS": "Bitstream Validated", 
  "STATUS_DT": "2025/06/26 14:30:45",
  "JOB_EVI": "{\"provider\":\"OSN\",\"action\":\"validation\",\"timestamp\":\"2025/06/26 14:30:45\",\"job_internal_id\":\"123\",\"retry_count\":\"0\",\"max_retries\":\"3\",\"evidence_found\":\"true\",\"evidence_customer_found\":\"true\",\"evidence_customer_name\":\"JOHN\",\"evidence_customer_surname\":\"DOE\",\"evidence_customer_email\":\"john.doe@example.com\",\"evidence_customer_mobile\":\"0821234567\",\"evidence_customer_address\":\"123 Main Street, Cape Town\",\"evidence_customer_circuit_number\":\"B310155685\",\"evidence_service_found\":\"true\",\"evidence_is_active\":\"true\",\"evidence_validation_status\":\"Bitstream Validated\",\"evidence_service_status\":\"active\",\"evidence_requires_cancellation\":\"true\",\"evidence_total_orders\":\"3\",\"evidence_new_installation_count\":\"1\",\"evidence_cease_orders_count\":\"0\"}"
}
```

#### **2. OSN Already Cancelled**
```json
{
  "JOB_ID": "OSN_VAL_002", 
  "FNO": "OSN",
  "STATUS": "Bitstream Already Cancelled",
  "STATUS_DT": "2025/06/26 14:30:45", 
  "JOB_EVI": "{\"provider\":\"OSN\",\"action\":\"validation\",\"timestamp\":\"2025/06/26 14:30:45\",\"job_internal_id\":\"124\",\"retry_count\":\"0\",\"max_retries\":\"3\",\"Captured_ID\":\"ORD123456789\",\"evidence_found\":\"true\",\"evidence_customer_found\":\"true\",\"evidence_customer_name\":\"JANE\",\"evidence_customer_surname\":\"SMITH\",\"evidence_customer_circuit_number\":\"B310155686\",\"evidence_service_found\":\"true\",\"evidence_is_active\":\"false\",\"evidence_validation_status\":\"Bitstream Already Cancelled\",\"evidence_service_status\":\"cancelled\",\"evidence_requires_cancellation\":\"false\",\"evidence_cease_implementation_date\":\"2025-01-15\",\"evidence_cease_order_status\":\"Implemented\"}"
}
```

#### **3. OSN Not Found**
```json
{
  "JOB_ID": "OSN_VAL_003",
  "FNO": "OSN", 
  "STATUS": "Bitstream Not Found",
  "STATUS_DT": "2025/06/26 14:30:45",
  "JOB_EVI": "{\"provider\":\"OSN\",\"action\":\"validation\",\"timestamp\":\"2025/06/26 14:30:45\",\"job_internal_id\":\"125\",\"retry_count\":\"0\",\"max_retries\":\"3\",\"search_attempted\":\"true\",\"search_result\":\"no_results_found\",\"circuit_number\":\"B999999999\",\"not_found_message\":\"Circuit not found\",\"operation_successful\":\"true\",\"found_service\":\"false\"}"
}
```

#### **4. OSN Error**
```json
{
  "JOB_ID": "OSN_VAL_004",
  "FNO": "OSN",
  "STATUS": "Bitstream Validation Timeout", 
  "STATUS_DT": "2025/06/26 14:30:45",
  "JOB_EVI": "{\"provider\":\"OSN\",\"action\":\"validation\",\"timestamp\":\"2025/06/26 14:30:45\",\"job_internal_id\":\"126\",\"retry_count\":\"2\",\"max_retries\":\"3\",\"error_occurred\":\"true\",\"error_message\":\"Portal timeout after 30 seconds\",\"error_type\":\"TIMEOUT_ERROR\",\"failed_at_step\":\"automation_execution\"}"
}
```

## **Oracle ORDS Handler** (Simple Approach)

```sql
BEGIN
  ORDS.define_handler(
    p_module_name    => 'rpa.v1',
    p_pattern        => 'job-status',
    p_method         => 'POST',
    p_source_type    => ORDS.source_type_plsql,
    p_source         => q'[
      BEGIN
        -- Insert using the 5 static fields only
        INSERT INTO rpa_job_status (job_id, fno, status, status_dt, job_evi)
        VALUES (:job_id, :fno, :status, :status_dt, :job_evi);
        
        :status_code := 200;
        :response := '{"result": "success", "job_id": "' || :job_id || '"}';
      EXCEPTION
        WHEN OTHERS THEN
          :status_code := 500;
          :response := '{"error": "Database error"}';
      END;]'
  );
  COMMIT;
END;
```

## **Key Points for Oracle Dev**

### **1. Use Only 5 Static Fields**
- Don't try to parse JOB_EVI initially
- Store entire JOB_EVI as CLOB
- Add parsing later if needed

### **2. JOB_EVI Size Requirements**
- OSN success cases: **5-10KB**
- Must use CLOB, not VARCHAR2(4000)

### **3. Error Fields Are Inside JOB_EVI**
- Not in the base payload
- All error handling is in the JSON string

### **4. Three Mutually Exclusive Scenarios**
- Error OR Not Found OR Success
- Never mixed together

**Start with the simple 5-field approach - it handles everything!**