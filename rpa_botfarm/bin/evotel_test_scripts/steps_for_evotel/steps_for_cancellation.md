
    # Step 1: Navigate to login page
    driver.get("https://my.evotel.co.za/Account/Login")
    WebDriverWait(driver, 10).until(EC.url_contains("Login"))

    # Step 2: Enter credentials
    email = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "#Email"))
    )
    email.clear()
    email.send_keys("vcappont2.bot@vcontractor.co.za")

    password = driver.find_element(By.CSS_SELECTOR, "#Password")
    password.clear()
    password.send_keys("Vodabot#01")

    # Step 3: Login
    login_btn = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//button[text()='Login']"))
    )
    login_btn.click()
    WebDriverWait(driver, 10).until(EC.url_contains("Manage/Index"))

    # Step 4: Search device
    search_field = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "#SearchString"))
    )
    search_field.clear()
    search_field.send_keys("48575443FF7B15AD")

    search_btn = driver.find_element(By.XPATH, "//*[text()='Search Serial']")
    search_btn.click()
    WebDriverWait(driver, 10).until(EC.url_contains("Search?SearchString"))

    # Step 5: Select service
    service_link = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//a[contains(.,'Vodacom Fibre')]"))
    )
    service_link.click()
    WebDriverWait(driver, 10).until(EC.url_contains("/Service/Info/"))

    # Step 6: Initiate cancellation
    cancel_btn = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//a[text()='Cancel Service']"))
    )
    cancel_btn.click()
    WebDriverWait(driver, 10).until(EC.url_contains("/Service/Cancel/"))

    # Step 7: Fill cancellation details
    reason_dropdown = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#CancellationReason"))
    )
    Select(reason_dropdown).select_by_visible_text("USING ANOTHER FNO")

    comment_field = driver.find_element(By.CSS_SELECTOR, "#CancellationComment")
    comment_field.clear()
    comment_field.send_keys("Bot cancellation")

    # Step 8: Confirm cancellation
    confirm_btn = driver.find_element(By.XPATH, "//input[@value='Confirm Cancellation']")
    confirm_btn.click()
    WebDriverWait(driver, 10).until(EC.url_contains("/Service/Info/"))

    # Step 9: Process work order
    work_order_link = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "#work-orders > span"))
    )
    work_order_link.click()

    order_number = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//a[contains(.,'20250805-')]"))
    )
    order_number.click()
    WebDriverWait(driver, 10).until(EC.title_contains("Manage Work Orders"))

    # Step 10: Update work order
    status_dropdown = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#StatusId"))
    )
    Select(status_dropdown).select_by_value("c14c051e-d259-426f-a2b1-e869e5300bcc")

    comments_field = driver.find_element(By.CSS_SELECTOR, "#Comments")
    comments_field.clear()
    comments_field.send_keys("Bot cancellation")

    notification_checkbox = driver.find_element(By.CSS_SELECTOR, "#NoUserNotification")
    if not notification_checkbox.is_selected():
        notification_checkbox.click()

    # Step 11: Submit work order
    submit_btn = driver.find_element(By.XPATH, "//input[@value='Submit']")
    submit_btn.click()
    WebDriverWait(driver, 10).until(EC.url_contains("success=0"))

    print("Cancellation process completed successfully!")
    time.sleep(3)

