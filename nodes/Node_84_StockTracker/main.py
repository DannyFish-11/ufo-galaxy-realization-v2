"""
Node 84: Stock Tracker - 股票追踪器
实时行情、技术指标、市场分析

功能：
1. 实时行情 - 股票价格、涨跌幅
2. 历史数据 - K线数据、历史价格
3. 技术指标 - MA、MACD、RSI、KDJ
4. 市场分析 - 涨跌榜、成交量
5. 自选股 - 自定义股票列表

优势：
- 多市场支持（A股、港股、美股）
- 实时更新
- 技术分析
- 数据可视化
"""

import os
import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import httpx

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "84")
NODE_NAME = os.getenv("NODE_NAME", "StockTracker")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Yahoo Finance API (免费)
YAHOO_API_BASE = "https://query1.finance.yahoo.com/v8/finance"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class StockQuote(BaseModel):
    symbol: str
    name: Optional[str] = None
    price: float
    change: float
    change_percent: float
    volume: Optional[int] = None
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    open: Optional[float] = None
    previous_close: Optional[float] = None
    timestamp: str

class HistoricalData(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    adj_close: Optional[float] = None

class TechnicalIndicators(BaseModel):
    symbol: str
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    ma50: Optional[float] = None
    rsi: Optional[float] = None
    macd: Optional[float] = None
    signal: Optional[float] = None
    timestamp: str

class Watchlist(BaseModel):
    name: str
    symbols: List[str]
    created_at: str
    updated_at: Optional[str] = None

# =============================================================================
# Stock Tracker Service
# =============================================================================

class StockTrackerService:
    """股票追踪服务"""
    
    def __init__(self):
        self.http_client = httpx.AsyncClient(timeout=30)
        self.quote_cache: Dict[str, StockQuote] = {}
        self.watchlists: Dict[str, Watchlist] = {}
        
        # 默认自选股
        self.watchlists["default"] = Watchlist(
            name="Default",
            symbols=["AAPL", "GOOGL", "MSFT", "TSLA"],
            created_at=datetime.now().isoformat()
        )
    
    async def get_quote(self, symbol: str) -> StockQuote:
        """获取实时行情"""
        try:
            # Yahoo Finance API
            url = f"{YAHOO_API_BASE}/quote"
            params = {"symbols": symbol}
            
            response = await self.http_client.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            if not data.get("quoteResponse", {}).get("result"):
                raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
            
            result = data["quoteResponse"]["result"][0]
            
            quote = StockQuote(
                symbol=symbol,
                name=result.get("shortName") or result.get("longName"),
                price=result.get("regularMarketPrice", 0.0),
                change=result.get("regularMarketChange", 0.0),
                change_percent=result.get("regularMarketChangePercent", 0.0),
                volume=result.get("regularMarketVolume"),
                market_cap=result.get("marketCap"),
                pe_ratio=result.get("trailingPE"),
                high=result.get("regularMarketDayHigh"),
                low=result.get("regularMarketDayLow"),
                open=result.get("regularMarketOpen"),
                previous_close=result.get("regularMarketPreviousClose"),
                timestamp=datetime.now().isoformat()
            )
            
            # 缓存
            self.quote_cache[symbol] = quote
            
            logger.info(f"Fetched quote for {symbol}: ${quote.price}")
            
            return quote
        
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching {symbol}: {e}")
            raise HTTPException(status_code=e.response.status_code, detail=str(e))
        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def get_historical(
        self,
        symbol: str,
        period: str = "1mo",
        interval: str = "1d"
    ) -> List[HistoricalData]:
        """获取历史数据"""
        try:
            # 计算时间范围
            period_map = {
                "1d": 1, "5d": 5, "1mo": 30, "3mo": 90,
                "6mo": 180, "1y": 365, "2y": 730, "5y": 1825
            }
            
            days = period_map.get(period, 30)
            end_time = int(datetime.now().timestamp())
            start_time = int((datetime.now() - timedelta(days=days)).timestamp())
            
            # Yahoo Finance Chart API
            url = f"{YAHOO_API_BASE}/chart/{symbol}"
            params = {
                "period1": start_time,
                "period2": end_time,
                "interval": interval
            }
            
            response = await self.http_client.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            if not data.get("chart", {}).get("result"):
                raise HTTPException(status_code=404, detail=f"No data for {symbol}")
            
            result = data["chart"]["result"][0]
            timestamps = result["timestamp"]
            quotes = result["indicators"]["quote"][0]
            
            historical = []
            for i, ts in enumerate(timestamps):
                date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                
                historical.append(HistoricalData(
                    date=date,
                    open=quotes["open"][i] or 0.0,
                    high=quotes["high"][i] or 0.0,
                    low=quotes["low"][i] or 0.0,
                    close=quotes["close"][i] or 0.0,
                    volume=quotes["volume"][i] or 0
                ))
            
            logger.info(f"Fetched {len(historical)} historical data points for {symbol}")
            
            return historical
        
        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    def calculate_ma(self, data: List[HistoricalData], period: int) -> Optional[float]:
        """计算移动平均线"""
        if len(data) < period:
            return None
        
        prices = [d.close for d in data[-period:]]
        return sum(prices) / period
    
    def calculate_rsi(self, data: List[HistoricalData], period: int = 14) -> Optional[float]:
        """计算 RSI 指标"""
        if len(data) < period + 1:
            return None
        
        # 计算价格变化
        changes = [data[i].close - data[i-1].close for i in range(1, len(data))]
        
        # 分离涨跌
        gains = [c if c > 0 else 0 for c in changes[-period:]]
        losses = [-c if c < 0 else 0 for c in changes[-period:]]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return round(rsi, 2)
    
    async def get_indicators(self, symbol: str) -> TechnicalIndicators:
        """获取技术指标"""
        try:
            # 获取历史数据
            historical = await self.get_historical(symbol, period="3mo", interval="1d")
            
            if not historical:
                raise HTTPException(status_code=404, detail="No historical data")
            
            # 计算指标
            indicators = TechnicalIndicators(
                symbol=symbol,
                ma5=self.calculate_ma(historical, 5),
                ma10=self.calculate_ma(historical, 10),
                ma20=self.calculate_ma(historical, 20),
                ma50=self.calculate_ma(historical, 50),
                rsi=self.calculate_rsi(historical),
                timestamp=datetime.now().isoformat()
            )
            
            return indicators
        
        except Exception as e:
            logger.error(f"Error calculating indicators for {symbol}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def get_market_movers(self, market: str = "US") -> Dict[str, List[str]]:
        """获取涨跌榜（简化版）"""
        # 这里使用预定义的热门股票列表
        popular_stocks = {
            "US": ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "META", "NVDA", "JPM"],
            "HK": ["0700.HK", "9988.HK", "0941.HK", "1810.HK"],
            "CN": ["000001.SS", "600519.SS", "000858.SZ"]
        }
        
        symbols = popular_stocks.get(market, popular_stocks["US"])
        
        # 获取所有股票行情
        quotes = []
        for symbol in symbols:
            try:
                quote = await self.get_quote(symbol)
                quotes.append(quote)
            except:
                pass
        
        # 排序
        gainers = sorted(quotes, key=lambda x: x.change_percent, reverse=True)[:5]
        losers = sorted(quotes, key=lambda x: x.change_percent)[:5]
        
        return {
            "gainers": [q.symbol for q in gainers],
            "losers": [q.symbol for q in losers]
        }
    
    def add_to_watchlist(self, name: str, symbol: str):
        """添加到自选股"""
        if name not in self.watchlists:
            self.watchlists[name] = Watchlist(
                name=name,
                symbols=[],
                created_at=datetime.now().isoformat()
            )
        
        if symbol not in self.watchlists[name].symbols:
            self.watchlists[name].symbols.append(symbol)
            self.watchlists[name].updated_at = datetime.now().isoformat()
            logger.info(f"Added {symbol} to watchlist {name}")
    
    def remove_from_watchlist(self, name: str, symbol: str):
        """从自选股移除"""
        if name in self.watchlists and symbol in self.watchlists[name].symbols:
            self.watchlists[name].symbols.remove(symbol)
            self.watchlists[name].updated_at = datetime.now().isoformat()
            logger.info(f"Removed {symbol} from watchlist {name}")
    
    async def close(self):
        """关闭客户端"""
        await self.http_client.aclose()

# =============================================================================
# FastAPI Application
# =============================================================================

tracker = StockTrackerService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting Node 84: Stock Tracker")
    yield
    await tracker.close()
    logger.info("Node 84 shutdown complete")

app = FastAPI(
    title="Node 84: Stock Tracker",
    description="股票追踪器 - 实时行情、技术指标、市场分析",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/")
async def root():
    return {
        "service": "Node 84: Stock Tracker",
        "status": "running",
        "markets": ["US", "HK", "CN"],
        "features": [
            "Real-time quotes",
            "Historical data",
            "Technical indicators",
            "Market movers",
            "Watchlist"
        ]
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "cached_quotes": len(tracker.quote_cache),
        "watchlists": len(tracker.watchlists),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/quote/{symbol}")
async def get_quote(symbol: str):
    """获取实时行情"""
    quote = await tracker.get_quote(symbol.upper())
    return quote.dict()

@app.get("/historical/{symbol}")
async def get_historical(
    symbol: str,
    period: str = "1mo",
    interval: str = "1d"
):
    """获取历史数据"""
    data = await tracker.get_historical(symbol.upper(), period, interval)
    return {
        "symbol": symbol,
        "period": period,
        "interval": interval,
        "data": [d.dict() for d in data],
        "count": len(data)
    }

@app.get("/indicators/{symbol}")
async def get_indicators(symbol: str):
    """获取技术指标"""
    indicators = await tracker.get_indicators(symbol.upper())
    return indicators.dict()

@app.get("/movers")
async def get_movers(market: str = "US"):
    """获取涨跌榜"""
    movers = await tracker.get_market_movers(market)
    return movers

@app.get("/watchlist")
async def get_watchlists():
    """获取所有自选股"""
    return {
        "watchlists": [w.dict() for w in tracker.watchlists.values()],
        "count": len(tracker.watchlists)
    }

@app.get("/watchlist/{name}")
async def get_watchlist(name: str):
    """获取指定自选股"""
    if name not in tracker.watchlists:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    
    watchlist = tracker.watchlists[name]
    
    # 获取所有股票行情
    quotes = []
    for symbol in watchlist.symbols:
        try:
            quote = await tracker.get_quote(symbol)
            quotes.append(quote.dict())
        except:
            pass
    
    return {
        "watchlist": watchlist.dict(),
        "quotes": quotes
    }

@app.post("/watchlist/{name}/add")
async def add_to_watchlist(name: str, symbol: str):
    """添加到自选股"""
    tracker.add_to_watchlist(name, symbol.upper())
    return {
        "message": "Added to watchlist",
        "watchlist": name,
        "symbol": symbol
    }

@app.delete("/watchlist/{name}/remove")
async def remove_from_watchlist(name: str, symbol: str):
    """从自选股移除"""
    tracker.remove_from_watchlist(name, symbol.upper())
    return {
        "message": "Removed from watchlist",
        "watchlist": name,
        "symbol": symbol
    }

# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8084)
