# PricesDropBot

PricesDropBot is a Python-based Amazon price monitoring bot. It automatically checks the prices of your favorite products and can either add them to your cart or purchase them for you when the price drops below a specified amount. It features a Telegram bot for notifications and interactions.

## Inspiration

This project is based on and inspired by the [AmazonAutoBuyBot GitHub project](https://github.com/davildf/Amazonautobuybot). While the original project provided a basic framework, PricesDropBot has been completely rewritten to include features like 2FA support, cookie-based session management, and a Telegram bot interface.

## Features

- **Price Monitoring**: Continuously monitors the prices of specified Amazon products.
- **Auto-Purchase/Add to Cart**: Automatically buys a product or adds it to the cart when the price drops below a set threshold.
- **2FA Support**: Handles Amazon's two-factor authentication.
- **Session Management**: Uses cookies to maintain login sessions and avoid repeated logins.
- **Telegram Bot**: Interact with the bot to add, remove, and list monitored products.
- **Flexible Configuration**: Uses a simple TOML file to manage the product list.
- **Debug Logging**: Saves HTML snapshots for debugging when elements are not found.

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/brushtyler/pricesdropbot.git
   cd pricesdropbot
   ```

2. **Create a virtual environment and activate it:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install the dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

1. **Environment Variables:**
   Create a `.env` file in the project root and add the following information:
   ```
   AMAZON_HOST="www.amazon.it"
   AMAZON_TAG="your-amazon-tag-21"
   AMAZON_EMAIL="your-amazon-email"
   AMAZON_PASSWORD="your-amazon-password"
   TELEGRAM_BOT_TOKEN="your-telegram-bot-token"
   TELEGRAM_CHAT_ID="your-telegram-chat-id"
   ```

2. **Products:**
   Create or edit `products.toml` to add the products you want to monitor. Use the following format for each product:
   ```toml
   ["Product Name"]
   asin = "B0XXXXXXXX"
   cut_price = 100.00
   autocheckout = false
   # Optional: specify desired product states
   # Valid states: "new", "used-like new", "used-very good", "used-good", "used-acceptable"
   object_state = ["new", "used-like new"]
   ```

## Usage

Run the main script:
```bash
python3 main.py
```
The bot will first handle the Amazon login (if necessary) and then start monitoring the products listed in `products.toml`.

## Telegram Bot Commands

- `/start`: Displays a welcome message.
- `/add`: Starts a conversation to add a new product to monitor.
- `/delete <ASIN>`: Deletes a product from the monitoring list.
- `/list`: Lists all the products currently being monitored.
- `/cancel`: Cancels the current operation (e.g., adding a product).

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
