#!/usr/bin/env python3

import selenium
from selenium.webdriver.common.by import By
from time import sleep
import threading
import os
import pickle

class pricesdrop_bot(threading.Thread):
    def __init__(self,amazon_host,amazon_tag,amazon_email,amazon_psw,asin,cut_price,autocheckout):
        self.amazon_host=amazon_host
        self.amazon_tag=amazon_tag
        self.amazon_email=amazon_email
        self.amazon_psw=amazon_psw
        self.asin=asin
        self.cut_price=cut_price
        self.autocheckout=autocheckout
        threading.Thread.__init__(self) 

    def run(self):
        options = selenium.webdriver.ChromeOptions() 
        options.headless = False

        # Configure the undetected_chromedriver options
        driver = selenium.webdriver.Chrome(options=options) 

        if os.path.exists(".cookies.pkl"):
            driver.get("https://"+self.amazon_host+"/")
            with open(".cookies.pkl", "rb") as f:
                cookies = pickle.load(f)
                for cookie in cookies:
                    if 'domain' in cookie and self.amazon_host not in cookie['domain']:
                        cookie['domain'] = '.' + self.amazon_host.replace('www.', '')
                    driver.add_cookie(cookie)
            driver.refresh()
        else:
            driver.get(f"https://{self.amazon_host}/ap/signin?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2F{self.amazon_host}%2Fgp%2Fcart%2Fview.html%2Fref%3Dnav_ya_signin%3F&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.assoc_handle=itflex&openid.mode=checkid_setup&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0")
            sleep(1)
            driver.find_element(by=By.XPATH, value='//*[@id="ap_email"]').send_keys(self.amazon_email)
            sleep(1)
            driver.find_element(by=By.XPATH, value='//*[@id="continue"]').click()
            sleep(1)
            driver.find_element(by=By.XPATH, value='//*[@id="ap_password"]').send_keys(self.amazon_psw)
            sleep(1)
            driver.find_element(by=By.XPATH, value='//*[@id="signInSubmit"]').click()

            input("Once 2FA step is completed (if any), press Enter to continue...") # Wait for 2FA

            # Save cookies to avoid always performing login+2FA
            with open(".cookies.pkl", "wb") as f:
                pickle.dump(driver.get_cookies(), f)

        check = True
        while check:
            sleep(2)
            try:
                driver.get(f"https://{self.amazon_host}/dp/{self.asin}/ref=olp-opf-redir?aod=1{f'&tag={self.amazon_tag}' if self.amazon_tag else ''}")
                sleep(3)

                # Check the main "Brand New" option (Featured Offer)
                try:
                    main_offer_container = driver.find_element(by=By.XPATH, value="//div[@id='aod-sticky-buybox']")
                    main_price_element = main_offer_container.find_element(by=By.XPATH, value=".//span[contains(@class, 'a-price-whole')]")
                    main_current_price = int(main_price_element.text.replace(".", "").replace(",", ""))

                    if main_current_price <= self.cut_price:
                        print(f"Price drop detected for main offer at: {main_current_price}")
                        main_add_to_cart_button = main_offer_container.find_element(by=By.XPATH, value=".//input[@id='aod-buybox-autocart-button']")
                        main_add_to_cart_button.click()
                        
                        sleep(0.5)
                        driver.find_element(by=By.XPATH, value='//*[@id="sc-buy-box-ptc-button"]/span/input').click()
                        if self.autocheckout == True:
                            driver.find_element(by=By.XPATH, value='//*[@id="a-autoid-0-announce"]').click()
                            driver.find_element(by=By.XPATH, value='//*[@id="submitOrderButtonId"]/span/input').click()
                        
                        check = False
                    else:
                        print(f"The current price for main offer is not low enough: {main_current_price}")
                except Exception as e:
                    print(f"Could not process main offer: {e}")

                if not check: # If main offer was processed and bought, exit
                    continue

                offer_containers = driver.find_elements(by=By.XPATH, value="//div[contains(@id, 'aod-offer-') and .//input[@name='submit.addToCart']]")
                print(f"{len(offer_containers)} other offers found")

                if not offer_containers:
                    driver.refresh()
                    sleep(2)
                    continue

                for offer in offer_containers:
                    try:
                        price_element = offer.find_element(by=By.XPATH, value=".//span[contains(@class, 'a-price-whole')]")
                        current_price = int(price_element.text.replace(".", "").replace(",", ""))

                        if current_price <= self.cut_price:
                            print(f"Price drop detected at: {current_price}")
                            add_to_cart_button = offer.find_element(by=By.XPATH, value=".//input[@name='submit.addToCart']")
                            add_to_cart_button.click()
                            
                            sleep(0.5)
                            driver.find_element(by=By.XPATH, value='//*[@id="sc-buy-box-ptc-button"]/span/input').click()
                            if self.autocheckout == True:
                                driver.find_element(by=By.XPATH, value='//*[@id="a-autoid-0-announce"]').click()
                                driver.find_element(by=By.XPATH, value='//*[@id="submitOrderButtonId"]/span/input').click()
                            
                            check = False
                            break
                        else:
                            print(f"The current price is not low enough: {current_price}")
                    except Exception as e:
                        print(f"Error processing an offer: {e}")
                
            except Exception as e:
                print(f"Error finding offers: {e}")
                driver.refresh()
                sleep(2)
            

        driver.quit()
    
        


amazon_host=os.getenv("AMAZON_HOST") or "www.amazon.it"
amazon_tag=os.getenv("AMAZON_TAG") or None

amazon_email=os.getenv("AMAZON_EMAIL")
amazon_psw=os.getenv("AMAZON_PASSWORD")

products = [
  { "asin": "B0DTKCCFMK", "cut_price": 50, "autocheckout": False },
]

threads_list=[]

for item in products:
    print(f"Start looking for price drop on product {item['asin']}: {('buy it' if item['autocheckout'] else 'add it to cart')} if price drops under {item['cut_price']}...")
    t=pricesdrop_bot(amazon_host=amazon_host, amazon_tag=amazon_tag, amazon_email=amazon_email, amazon_psw=amazon_psw, asin=item["asin"], cut_price=item["cut_price"], autocheckout=item["autocheckout"])
    t.start() 
    threads_list.append(t) 
  
for t in threads_list: 
    t.join()
       
