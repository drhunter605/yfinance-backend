from http.server import BaseHTTPRequestHandler
import json
import yfinance as yf
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta
import pandas as pd

# This custom JSON encoder is needed to handle pandas Timestamps, which are not standard JSON.
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, pd.Timestamp)):
            return obj.isoformat()
        return json.JSONEncoder.default(self, obj)

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """
        Handles GET requests to the serverless function.
        Expects a 'ticker' query parameter, e.g., /api/handler?ticker=AAPL
        """
        # Set CORS headers for all responses
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header("Access-Control-Allow-Headers", "X-Requested-With, Content-type")
        
        # Handle pre-flight OPTIONS request for CORS
        if self.command == 'OPTIONS':
            self.send_response(200)
            self.end_headers()
            return
            
        # Parse the ticker from the URL query string
        query_components = parse_qs(urlparse(self.path).query)
        ticker_symbol = query_components.get('ticker', [None])[0]

        if not ticker_symbol:
            self.send_response(400)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Ticker symbol is required"}).encode('utf-8'))
            return

        try:
            # --- Fetch data using yfinance ---
            stock = yf.Ticker(ticker_symbol)

            # 1. Get historical market data (2 years for better performance)
            end_date = datetime.today()
            start_date = end_date - timedelta(days=2*365)
            history_df = stock.history(start=start_date.strftime('%Y-%m-%d'), end=end_date.strftime('%Y-%m-%d'))
            
            history_df.reset_index(inplace=True)
            history_df['Date'] = pd.to_datetime(history_df['Date'])
            
            history_df.rename(columns={
                'Date': 'date', 'Open': 'open', 'High': 'high', 
                'Low': 'low', 'Close': 'close', 'Volume': 'volume'
            }, inplace=True)
            historical_data = history_df[['date', 'open', 'high', 'low', 'close', 'volume']].to_dict('records')

            # 2. Get options data for the nearest expiration date
            expiration_dates = stock.options
            if not expiration_dates:
                 raise ValueError("No options data available for this ticker.")
            
            nearest_expiration = expiration_dates[0]
            options_chain = stock.option_chain(nearest_expiration)

            calls_df = options_chain.calls[['strike', 'lastPrice', 'volume', 'openInterest', 'impliedVolatility']]
            puts_df = options_chain.puts[['strike', 'lastPrice', 'volume', 'openInterest', 'impliedVolatility']]

            options_data = {
                'calls': calls_df.to_dict('records'),
                'puts': puts_df.to_dict('records')
            }
            
            # 3. Get latest news
            news = stock.news[:5] # Get top 5 news articles
            news_data = [{
                "title": item.get('title'),
                "publisher": item.get('publisher'),
                "link": item.get('link'),
                "published_utc": datetime.fromtimestamp(item.get('providerPublishTime')).isoformat()
            } for item in news]


            # --- Prepare the final JSON response ---
            response_data = {
                "historicalData": historical_data,
                "options": options_data,
                "expirationDate": nearest_expiration,
                "news": news_data
            }

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response_data, cls=CustomJSONEncoder).encode('utf-8'))

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            
        return
