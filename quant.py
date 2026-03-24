import requests
import json
import csv
import os
import sys
import time
from datetime import datetime

# Windows下禁用快速编辑模式
if os.name == 'nt':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        STD_INPUT_HANDLE = -10
        ENABLE_EXTENDED_FLAGS = 0x0080
        handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        kernel32.SetConsoleMode(handle, ENABLE_EXTENDED_FLAGS)
    except:
        pass

class PersistentMarketMonitor:
    """全A股监控系统（完整配置从CSV读取）"""

    def __init__(self, config_file='config.csv', position_file='position.py'):
        self.config_file = config_file
        self.position_file = position_file

        # 从CSV加载配置
        self.load_config()

        # 加载交易状态
        self.load_state()

        # 加载初始持仓配置（如果有position.py）
        self.load_initial_positions()

        # 运行参数
        self.running = False

        # 市场数据
        self.market_data = {}
        self.last_update = None
        self.valid_codes = []

        # 加载股票代码
        self.load_stock_codes()

    def load_initial_positions(self):
        """从position.csv加载初始持仓"""
        if os.path.exists(self.position_file):
            try:
                # 动态导入position.csv
                import importlib.util
                spec = importlib.util.spec_from_file_location("position_config", self.position_file)
                position_config = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(position_config)

                initial_positions = getattr(position_config, 'INITIAL_POSITIONS', {})

                if initial_positions:
                    print(f"✅ 检测到position.csv，加载初始持仓: {len(initial_positions)} 只")

                    # 合并到现有持仓
                    for code, pos_data in initial_positions.items():
                        if code not in self.positions:
                            self.positions[code] = {
                                'shares': pos_data.get('shares', 0),
                                'buy_price': pos_data.get('buy_price', 0),
                                'buy_time': datetime.now(),
                                'name': pos_data.get('name', code)
                            }
                            print(f"   添加持仓: {code} {pos_data.get('name', '')} {pos_data.get('shares', 0)}股")

                    # 保存更新后的状态
                    self.save_state()
                    self.save_positions_csv()

                else:
                    print(f"📝 position.csv存在但INITIAL_POSITIONS为空，跳过加载")

            except Exception as e:
                print(f"❌ 加载position.csv失败: {e}")
        else:
            print(f"📝 未找到{self.position_file}，按空仓启动")
            # 创建空的position.csv文件
            self.create_empty_position_file()

    def create_empty_position_file(self):
        """创建空的position.csv文件"""
        try:
            with open(self.position_file, 'w', encoding='utf-8') as f:
                f.write('''# position.csv
# 持仓配置文件
# 程序启动时会读取这个文件，按持仓继续模拟操作

INITIAL_POSITIONS = {
    # 格式: '股票代码': {'shares': 持仓数量, 'buy_price': 买入价格, 'name': '股票名称'}

    # 示例（取消注释即可使用）：
    # '600519': {'shares': 100, 'buy_price': 1800.0, 'name': '贵州茅台'},
    # '000858': {'shares': 200, 'buy_price': 150.0, 'name': '五粮液'},

}
''')
            print(f"✅ 已创建 {self.position_file}")
        except Exception as e:
            print(f"❌ 创建{self.position_file}失败: {e}")

    def load_config(self):
        """从CSV加载配置"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    config = {}
                    for row in reader:
                        if len(row) >= 2 and row[0] and not row[0].startswith('#'):
                            key = row[0].strip()
                            value = row[1].strip()
                            config[key] = value

                self.initial_capital = float(config.get('initial_capital', 100000))
                self.update_interval = int(config.get('update_interval', 60))
                self.max_position = int(config.get('max_position', 5))
                self.position_size = float(config.get('position_size', 0.2))
                self.stop_loss = float(config.get('stop_loss', -0.05))
                self.take_profit = float(config.get('take_profit', 0.10))
                self.buy_score = int(config.get('buy_score', 65))
                self.score_pct_min = float(config.get('score_pct_min', 1.0))
                self.score_pct_max = float(config.get('score_pct_max', 6.0))
                self.score_pct_min_small = float(config.get('score_pct_min_small', 0.0))
                self.score_pct_max_small = float(config.get('score_pct_max_small', 1.0))
                self.score_pct_big = float(config.get('score_pct_big', 9.5))
                self.score_pct_down = float(config.get('score_pct_down', -5.0))
                self.score_pct_points = int(config.get('score_pct_points', 25))
                self.score_pct_small_points = int(config.get('score_pct_small_points', 10))
                self.score_turnover_min = float(config.get('score_turnover_min', 2.0))
                self.score_turnover_max = float(config.get('score_turnover_max', 10.0))
                self.score_turnover_points = int(config.get('score_turnover_points', 20))
                self.score_amount_min = float(config.get('score_amount_min', 300000000))
                self.score_amount_points = int(config.get('score_amount_points', 15))
                self.score_open_points = int(config.get('score_open_points', 10))
                self.score_high_pct = float(config.get('score_high_pct', 0.98))
                self.score_high_points = int(config.get('score_high_points', 10))
                self.score_pe_min = float(config.get('score_pe_min', 5.0))
                self.score_pe_max = float(config.get('score_pe_max', 60.0))
                self.score_pe_points = int(config.get('score_pe_points', 10))
                self.score_cap_min = float(config.get('score_cap_min', 50.0))
                self.score_cap_max = float(config.get('score_cap_max', 2000.0))
                self.score_cap_points = int(config.get('score_cap_points', 10))
                self.state_file = config.get('state_file', 'trading_state.json')
                self.positions_file = config.get('positions_file', 'positions.csv')
                self.trades_file = config.get('trades_file', 'trades.csv')

                print(f"✅ 加载配置成功: {self.config_file}")
                print(f"   初始资金: ¥{self.initial_capital:,.0f}")
                print(f"   买入评分: >= {self.buy_score}分")
            except Exception as e:
                print(f"❌ 加载配置失败: {e}")
                self.init_default_config()
        else:
            print("📝 配置文件不存在，创建默认配置")
            self.init_default_config()

    def init_default_config(self):
        """初始化默认配置"""
        self.initial_capital = 100000
        self.update_interval = 60
        self.max_position = 5
        self.position_size = 0.2
        self.stop_loss = -0.05
        self.take_profit = 0.10
        self.buy_score = 65
        self.score_pct_min = 1.0
        self.score_pct_max = 6.0
        self.score_pct_min_small = 0.0
        self.score_pct_max_small = 1.0
        self.score_pct_big = 9.5
        self.score_pct_down = -5.0
        self.score_pct_points = 25
        self.score_pct_small_points = 10
        self.score_turnover_min = 2.0
        self.score_turnover_max = 10.0
        self.score_turnover_points = 20
        self.score_amount_min = 300000000
        self.score_amount_points = 15
        self.score_open_points = 10
        self.score_high_pct = 0.98
        self.score_high_points = 10
        self.score_pe_min = 5.0
        self.score_pe_max = 60.0
        self.score_pe_points = 10
        self.score_cap_min = 50.0
        self.score_cap_max = 2000.0
        self.score_cap_points = 10
        self.state_file = 'trading_state.json'
        self.positions_file = 'positions.csv'
        self.trades_file = 'trades.csv'
        self.save_config()

    def save_config(self):
        """保存配置到CSV"""
        try:
            with open(self.config_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['参数名', '参数值', '说明'])
                writer.writerow(['initial_capital', self.initial_capital, '初始资金(元)'])
                writer.writerow(['update_interval', self.update_interval, '更新间隔(秒)'])
                writer.writerow(['max_position', self.max_position, '最大持仓数量'])
                writer.writerow(['position_size', self.position_size, '单票仓位比例'])
                writer.writerow(['stop_loss', self.stop_loss, '止损比例'])
                writer.writerow(['take_profit', self.take_profit, '止盈比例'])
                writer.writerow(['buy_score', self.buy_score, '买入最低评分'])
                writer.writerow(['score_pct_min', self.score_pct_min, '涨幅适中下限(%)'])
                writer.writerow(['score_pct_max', self.score_pct_max, '涨幅适中上限(%)'])
                writer.writerow(['score_pct_min_small', self.score_pct_min_small, '小涨幅下限(%)'])
                writer.writerow(['score_pct_max_small', self.score_pct_max_small, '小涨幅上限(%)'])
                writer.writerow(['score_pct_big', self.score_pct_big, '涨停阈值(%)'])
                writer.writerow(['score_pct_down', self.score_pct_down, '跌幅阈值(%)'])
                writer.writerow(['score_pct_points', self.score_pct_points, '涨幅适中分数'])
                writer.writerow(['score_pct_small_points', self.score_pct_small_points, '小涨幅分数'])
                writer.writerow(['score_turnover_min', self.score_turnover_min, '换手率下限(%)'])
                writer.writerow(['score_turnover_max', self.score_turnover_max, '换手率上限(%)'])
                writer.writerow(['score_turnover_points', self.score_turnover_points, '换手率分数'])
                writer.writerow(['score_amount_min', self.score_amount_min, '放量阈值(元)'])
                writer.writerow(['score_amount_points', self.score_amount_points, '放量分数'])
                writer.writerow(['score_open_points', self.score_open_points, '高开分数'])
                writer.writerow(['score_high_pct', self.score_high_pct, '接近新高比例'])
                writer.writerow(['score_high_points', self.score_high_points, '新高分数'])
                writer.writerow(['score_pe_min', self.score_pe_min, 'PE下限'])
                writer.writerow(['score_pe_max', self.score_pe_max, 'PE上限'])
                writer.writerow(['score_pe_points', self.score_pe_points, 'PE分数'])
                writer.writerow(['score_cap_min', self.score_cap_min, '市值下限(亿)'])
                writer.writerow(['score_cap_max', self.score_cap_max, '市值上限(亿)'])
                writer.writerow(['score_cap_points', self.score_cap_points, '市值分数'])
                writer.writerow(['state_file', self.state_file, '状态文件'])
                writer.writerow(['positions_file', self.positions_file, '持仓文件'])
                writer.writerow(['trades_file', self.trades_file, '交易记录文件'])
            print(f"✅ 配置已保存: {self.config_file}")
        except Exception as e:
            print(f"❌ 保存配置失败: {e}")

    def load_stock_codes(self):
        """加载股票代码列表"""
        if os.path.exists('a_stock_codes.json'):
            try:
                with open('a_stock_codes.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.valid_codes = [item['code'] for item in data]
                print(f"✅ 加载股票代码: {len(self.valid_codes)} 只")
                return
            except Exception as e:
                print(f"❌ 加载代码失败: {e}")
        print("📝 正在获取股票代码...")
        self.fetch_all_stock_codes()

    def fetch_all_stock_codes(self):
        """获取所有A股代码"""
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        prefixes = ['600', '601', '603', '605', '000', '001', '002', '003']
        all_candidates = []
        for prefix in prefixes:
            for i in range(1000):
                all_candidates.append(f"{prefix}{i:03d}")
        print(f"待验证: {len(all_candidates)} 个代码")
        valid_codes = []
        batch_size = 800
        for start in range(0, len(all_candidates), batch_size):
            batch = all_candidates[start:start + batch_size]
            code_list = []
            for c in batch:
                market = 'sh' if c.startswith('6') else 'sz'
                code_list.append(f'{market}{c}')
            url = f'https://qt.gtimg.cn/q={",".join(code_list)}'
            try:
                r = requests.get(url, headers=headers, timeout=10)
                for line in r.text.strip().split('\n'):
                    if '=' not in line or '~' not in line:
                        continue
                    parts = line.split('=')[1].strip('"').split('~')
                    if len(parts) < 4:
                        continue
                    code = parts[2]
                    name = parts[1]
                    if name and code:
                        valid_codes.append(code)
                pct = min(100, (start + batch_size) * 100 // len(all_candidates))
                print(f"\r  进度: {pct}%  已找到 {len(valid_codes)} 只", end='', flush=True)
            except Exception as e:
                print(f"\n  批次获取失败，跳过: {e}")
                continue
            time.sleep(0.2)
        print(f"\n\n✅ 获取完成: {len(valid_codes)} 只主板股票")
        data = [{'code': c} for c in valid_codes]
        with open('a_stock_codes.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        self.valid_codes = valid_codes

    def load_state(self):
        """加载交易状态"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                self.capital = state.get('capital', self.initial_capital)
                self.positions = state.get('positions', {})
                self.trades = state.get('trades', [])
                for code, pos in self.positions.items():
                    if 'buy_time' in pos:
                        pos['buy_time'] = datetime.fromisoformat(pos['buy_time'])
                for trade in self.trades:
                    if 'time' in trade:
                        trade['time'] = datetime.fromisoformat(trade['time'])
                print(f"✅ 加载状态成功")
                print(f"   可用资金: ¥{self.capital:,.2f}")
                print(f"   持仓: {len(self.positions)} 只")
                print(f"   交易: {len(self.trades)} 笔")
            except Exception as e:
                print(f"❌ 加载状态失败: {e}")
                self.init_new_state()
        else:
            print("📝 新用户，初始化状态")
            self.init_new_state()

    def init_new_state(self):
        """初始化新状态"""
        self.capital = self.initial_capital
        self.positions = {}
        self.trades = []

    def save_state(self):
        """保存状态到JSON"""
        try:
            state = {
                'capital': self.capital,
                'positions': {},
                'trades': [],
                'last_saved': datetime.now().isoformat()
            }
            for code, pos in self.positions.items():
                state['positions'][code] = pos.copy()
                if 'buy_time' in state['positions'][code]:
                    state['positions'][code]['buy_time'] = pos['buy_time'].isoformat()
            for trade in self.trades:
                state['trades'].append(trade.copy())
                if 'time' in state['trades'][-1]:
                    state['trades'][-1]['time'] = trade['time'].isoformat()
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"❌ 保存失败: {e}")
            return False

    def save_positions_csv(self):
        """保存持仓到CSV"""
        try:
            now = datetime.now()
            with open(self.positions_file, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['更新时间', '股票代码', '股票名称', '持仓数量', '买入价格', '买入时间', '当前价格', '持仓市值', '盈亏金额', '盈亏比例(%)'])
                total_cost = 0
                total_market_value = 0
                for code, pos in self.positions.items():
                    current_price = pos['buy_price']
                    if code in self.market_data:
                        current_price = self.market_data[code]['price']
                    market_value = pos['shares'] * current_price
                    cost = pos['shares'] * pos['buy_price']
                    profit = market_value - cost
                    profit_pct = (current_price - pos['buy_price']) / pos['buy_price'] * 100
                    total_cost += cost
                    total_market_value += market_value
                    buy_time_str = ''
                    if isinstance(pos['buy_time'], datetime):
                        buy_time_str = pos['buy_time'].strftime('%Y-%m-%d %H:%M:%S')
                    writer.writerow([now.strftime('%Y-%m-%d %H:%M:%S'), code, pos['name'], pos['shares'],
                                   f"{pos['buy_price']:.2f}", buy_time_str, f"{current_price:.2f}",
                                   f"{market_value:.2f}", f"{profit:.2f}", f"{profit_pct:.2f}"])
                if self.positions:
                    writer.writerow([])
                    total_profit = total_market_value - total_cost
                    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0
                    writer.writerow(['汇总', '', '', '', '', '', '', f"{total_market_value:.2f}", f"{total_profit:.2f}", f"{total_profit_pct:.2f}"])
                writer.writerow([])
                total_value = self.capital + total_market_value
                account_profit = total_value - self.initial_capital
                account_profit_pct = (account_profit / self.initial_capital * 100)
                writer.writerow(['账户汇总', '', '', '', '', '', '', f"总资产: {total_value:.2f}", f"可用资金: {self.capital:.2f}", f"总收益: {account_profit_pct:.2f}%"])
            return True
        except Exception as e:
            print(f"❌ 保存持仓CSV失败: {e}")
            return False

    def save_trade_csv(self, trade):
        """保存单笔交易到CSV"""
        try:
            file_exists = os.path.exists(self.trades_file)
            with open(self.trades_file, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(['交易时间', '交易类型', '股票代码', '股票名称', '交易价格', '交易数量', '交易金额', '盈亏金额', '盈亏比例(%)', '交易原因'])
                amount = trade['price'] * trade['shares']
                if trade['type'] == 'BUY':
                    writer.writerow([trade['time'].strftime('%Y-%m-%d %H:%M:%S'), '买入', trade['code'], trade['name'],
                                   f"{trade['price']:.2f}", trade['shares'], f"{amount:.2f}", '', '', trade.get('reason', '')])
                else:
                    writer.writerow([trade['time'].strftime('%Y-%m-%d %H:%M:%S'), '卖出', trade['code'], trade['name'],
                                   f"{trade['price']:.2f}", trade['shares'], f"{amount:.2f}",
                                   f"{trade.get('profit', 0):.2f}", f"{trade.get('profit_rate', 0)*100:.2f}", trade.get('reason', '')])
            return True
        except Exception as e:
            print(f"❌ 保存交易CSV失败: {e}")
            return False

    def safe_float(self, value):
        """安全转换浮点数"""
        try:
            if value in ['-', '', None, '--']:
                return 0.0
            return float(value)
        except:
            return 0.0

    def get_market_data(self):
        """获取实时行情"""
        try:
            print("  获取市场数据...")
            if not self.valid_codes:
                print("  无有效股票代码")
                return False
            all_stocks = {}
            batch_size = 800
            success_batches = 0
            failed_batches = 0
            for start in range(0, len(self.valid_codes), batch_size):
                batch = self.valid_codes[start:start + batch_size]
                code_list = []
                for code in batch:
                    market = 'sh' if code.startswith('6') else 'sz'
                    code_list.append(f'{market}{code}')
                url = f'https://qt.gtimg.cn/q={",".join(code_list)}'
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                try:
                    r = requests.get(url, headers=headers, timeout=10)
                    for line in r.text.strip().split('\n'):
                        if '=' not in line or '~' not in line:
                            continue
                        parts = line.split('=')[1].strip('"').split('~')
                        if len(parts) < 50:
                            continue
                        code = parts[2]
                        name = parts[1]
                        price = self.safe_float(parts[3])
                        if price <= 0:
                            continue
                        all_stocks[code] = {
                            'code': code, 'name': name, 'price': price,
                            'change_pct': self.safe_float(parts[32]),
                            'volume': self.safe_float(parts[6]) * 100,
                            'amount': self.safe_float(parts[37]) * 10000,
                            'turnover': self.safe_float(parts[38]),
                            'pe': self.safe_float(parts[39]),
                            'high': self.safe_float(parts[33]),
                            'low': self.safe_float(parts[34]),
                            'open': self.safe_float(parts[5]),
                            'pre_close': self.safe_float(parts[4]),
                            'market_cap': self.safe_float(parts[45]) * 10000,
                        }
                    success_batches += 1
                except Exception as e:
                    failed_batches += 1
                    continue
                time.sleep(0.1)
            if all_stocks:
                self.market_data = all_stocks
                self.last_update = datetime.now()
                print(f"  ✅ 获取: {len(all_stocks)} 只 ({success_batches}批成功, {failed_batches}批失败)")
                return True
            else:
                print(f"  ⚠️ 未获取到数据")
                return False
        except Exception as e:
            print(f"  ❌ 获取异常: {e}")
            return False

    def calculate_score(self, stock):
        """计算股票评分"""
        score = 0
        reasons = []
        change_pct = stock['change_pct']
        turnover = stock['turnover']
        amount = stock['amount']
        price = stock['price']
        open_price = stock['open']
        high = stock['high']
        pe = stock['pe']

        if 'ST' in stock['name'] or '*ST' in stock['name']:
            return 0, ['ST']
        if change_pct >= self.score_pct_big:
            return 0, ['涨停']
        if change_pct <= self.score_pct_down:
            return 0, ['跌幅大']

        if self.score_pct_min <= change_pct <= self.score_pct_max:
            score += self.score_pct_points
            reasons.append(f'涨{change_pct:.1f}%')
        elif self.score_pct_min_small <= change_pct < self.score_pct_max_small:
            score += self.score_pct_small_points
            reasons.append('小涨')

        if self.score_turnover_min <= turnover <= self.score_turnover_max:
            score += self.score_turnover_points
            reasons.append(f'换{turnover:.1f}%')

        if amount > self.score_amount_min:
            score += self.score_amount_points
            reasons.append('放量')

        if price > open_price:
            score += self.score_open_points
            reasons.append('高开')

        if high > 0 and price >= high * self.score_high_pct:
            score += self.score_high_points
            reasons.append('新高')

        if self.score_pe_min <= pe <= self.score_pe_max:
            score += self.score_pe_points
            reasons.append('PE合理')

        cap = stock['market_cap'] / 1e8
        if self.score_cap_min <= cap <= self.score_cap_max:
            score += self.score_cap_points
            reasons.append('市值适中')

        return score, reasons

    def generate_signals(self):
        """生成交易信号"""
        buy_signals = []
        sell_signals = []

        for code, pos in list(self.positions.items()):
            if code in self.market_data:
                stock = self.market_data[code]
                profit = (stock['price'] - pos['buy_price']) / pos['buy_price']
                if profit <= self.stop_loss:
                    sell_signals.append({'code': code, 'name': stock['name'], 'price': stock['price'], 'reason': f'止损{profit:.2%}', 'profit_rate': profit})
                elif profit >= self.take_profit:
                    sell_signals.append({'code': code, 'name': stock['name'], 'price': stock['price'], 'reason': f'止盈{profit:.2%}', 'profit_rate': profit})

        for code, stock in self.market_data.items():
            if code in self.positions:
                continue
            score, reasons = self.calculate_score(stock)
            if score >= self.buy_score:
                buy_signals.append({'code': code, 'name': stock['name'], 'price': stock['price'], 'score': score, 'reasons': reasons})

        buy_signals.sort(key=lambda x: x['score'], reverse=True)
        return buy_signals, sell_signals

    def execute_buy(self, signal):
        """执行买入"""
        code = signal['code']
        price = signal['price']
        position_amount = self.initial_capital * self.position_size
        shares = int(position_amount / price / 100) * 100
        if shares < 100:
            return False
        cost = shares * price
        if cost > self.capital:
            return False
        self.positions[code] = {'shares': shares, 'buy_price': price, 'buy_time': datetime.now(), 'name': signal['name']}
        self.capital -= cost
        trade = {'time': datetime.now(), 'type': 'BUY', 'code': code, 'name': signal['name'], 'price': price, 'shares': shares, 'reason': '+'.join(signal['reasons'][:3]), 'score': signal['score']}
        self.trades.append(trade)
        self.save_state()
        self.save_trade_csv(trade)
        self.save_positions_csv()
        return True

    def execute_sell(self, signal):
        """执行卖出"""
        code = signal['code']
        if code not in self.positions:
            return False
        pos = self.positions[code]
        price = signal['price']
        shares = pos['shares']
        revenue = shares * price
        profit = revenue - shares * pos['buy_price']
        self.capital += revenue
        trade = {'time': datetime.now(), 'type': 'SELL', 'code': code, 'name': pos['name'], 'price': price, 'shares': shares, 'profit': profit, 'profit_rate': signal['profit_rate'], 'reason': signal['reason']}
        self.trades.append(trade)
        del self.positions[code]
        self.save_state()
        self.save_trade_csv(trade)
        self.save_positions_csv()
        return True

    def clear_screen(self):
        """清屏"""
        print('\033[2J\033[H', end='')

    def display_status(self, buy_signals, sell_signals):
        """显示状态"""
        now = datetime.now()
        total = len(self.market_data)
        up = sum(1 for s in self.market_data.values() if s['change_pct'] > 0)
        down = sum(1 for s in self.market_data.values() if s['change_pct'] < 0)
        flat = total - up - down
        limit_up = sum(1 for s in self.market_data.values() if s['change_pct'] >= 9.9)
        limit_down = sum(1 for s in self.market_data.values() if s['change_pct'] <= -9.9)
        pos_value = 0
        for code, pos in self.positions.items():
            if code in self.market_data:
                pos_value += pos['shares'] * self.market_data[code]['price']
            else:
                pos_value += pos['shares'] * pos['buy_price']
        total_value = self.capital + pos_value
        ret = (total_value - self.initial_capital) / self.initial_capital * 100
        self.clear_screen()
        print("="*70)
        print(f"  全A股监控系统 | {now.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  配置: {self.config_file} | 买入评分>= {self.buy_score}分")
        print("="*70)
        print(f"\n  市场: {total}只 | 上{up} | 下{down} | 平{flat} | 涨停{limit_up} | 跌停{limit_down}")
        print(f"  账户: 可用{self.capital:,.0f} | 持仓{pos_value:,.0f} | 总资产{total_value:,.0f} | 收益{ret:+.2f}%")
        if self.positions:
            print(f"\n  持仓({len(self.positions)}只):")
            for code, pos in self.positions.items():
                if code in self.market_data:
                    cur = self.market_data[code]['price']
                    pr = (cur - pos['buy_price']) / pos['buy_price'] * 100
                    emoji = '+' if pr >= 0 else '-'
                    print(f"    [{emoji}] {code} {pos['name']:<8} {pos['shares']}股 成本:{pos['buy_price']:.2f} 现价:{cur:.2f} {pr:+.2f}%")
        top5 = sorted(self.market_data.values(), key=lambda x: x['change_pct'], reverse=True)[:5]
        print(f"\n  涨幅前5:")
        for s in top5:
            print(f"    {s['code']} {s['name']:<10} {s['price']:>8.2f} +{s['change_pct']:.2f}%")
        print(f"\n  买入信号(>={self.buy_score}分):")
        for s in buy_signals[:5]:
            print(f"    [+] {s['code']} {s['name']:<10} {s['score']}分 | {', '.join(s['reasons'][:3])}")
        if sell_signals:
            print(f"\n  卖出信号:")
            for s in sell_signals:
                print(f"    [-] {s['code']} {s['name']} | {s['reason']}")
        if self.trades:
            print(f"\n  最近交易:")
            for t in self.trades[-3:]:
                if t['type'] == 'BUY':
                    print(f"    {t['time'].strftime('%H:%M:%S')} 买入 {t['code']} {t['name']:<8} {t['shares']}股 @ {t['price']:.2f}")
                else:
                    emoji = '+' if t.get('profit', 0) >= 0 else '-'
                    print(f"    {t['time'].strftime('%H:%M:%S')} {emoji}卖出 {t['code']} {t['name']:<8} {t.get('profit_rate', 0):+.2%}")
        print(f"\n  {self.update_interval}秒后更新 | Ctrl+C停止")

    def run(self):
        """运行监控"""
        self.running = True
        self.save_positions_csv()
        print("\n" + "="*70)
        print("  全A股监控系统（完整配置版）")
        print("="*70)
        print(f"  配置文件: {self.config_file}")
        print(f"  持仓配置: {self.position_file}")
        print(f"  初始资金: ¥{self.initial_capital:,.0f}")
        print(f"  买入评分: >= {self.buy_score}分")
        print(f"  更新间隔: {self.update_interval}秒")
        print("="*70)
        last_save_time = time.time()
        try:
            while self.running:
                now = datetime.now()
                current_time = now.hour * 100 + now.minute
                is_trading = (930 <= current_time <= 1130) or (1300 <= current_time <= 1500)
                if not is_trading:
                    self.clear_screen()
                    print("="*70)
                    print("  全A股监控系统（完整配置版）")
                    print("="*70)
                    print(f"\n  当前: {now.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"\n  非交易时间")
                    print(f"  交易: 09:30-11:30, 13:00-15:00")
                    print(f"\n  等待开盘...")
                    print(f"  配置文件: {self.config_file}")
                    if time.time() - last_save_time >= 60:
                        self.save_positions_csv()
                        last_save_time = time.time()
                    time.sleep(60)
                    continue
                print(f"\n获取数据... {now.strftime('%H:%M:%S')}")
                success = self.get_market_data()
                if success:
                    buy_signals, sell_signals = self.generate_signals()
                    for signal in sell_signals:
                        if self.execute_sell(signal):
                            print(f"\n  卖出: {signal['code']} {signal['name']} | {signal['reason']}")
                    buy_count = 0
                    for signal in buy_signals:
                        if len(self.positions) >= self.max_position:
                            break
                        if buy_count >= 1:
                            break
                        if self.execute_buy(signal):
                            print(f"\n  买入: {signal['code']} {signal['name']} @ {signal['price']:.2f}")
                            buy_count += 1
                    self.display_status(buy_signals, sell_signals)
                else:
                    print("  数据获取失败")
                    self.display_status([], [])
                if time.time() - last_save_time >= 60:
                    self.save_positions_csv()
                    last_save_time = time.time()
                    print(f"\n  ✅ 持仓已更新: {self.positions_file}")
                time.sleep(self.update_interval)
        except KeyboardInterrupt:
            print("\n\n停止运行")
            self.save_state()
            self.save_positions_csv()
            self.print_summary()

    def print_summary(self):
        """打印汇总"""
        print("\n" + "="*70)
        print("  交易汇总")
        print("="*70)
        buys = [t for t in self.trades if t['type'] == 'BUY']
        sells = [t for t in self.trades if t['type'] == 'SELL']
        print(f"  买入: {len(buys)}笔 | 卖出: {len(sells)}笔")
        if sells:
            wins = [t for t in sells if t.get('profit', 0) > 0]
            total_profit = sum(t.get('profit', 0) for t in sells)
            print(f"  盈利: {len(wins)}笔 | 亏损: {len(sells)-len(wins)}笔")
            print(f"  胜率: {len(wins)/len(sells)*100:.1f}%")
            print(f"  总盈亏: {total_profit:+,.0f}")
        pos_value = 0
        for code, pos in self.positions.items():
            if code in self.market_data:
                pos_value += pos['shares'] * self.market_data[code]['price']
            else:
                pos_value += pos['shares'] * pos['buy_price']
        final_value = self.capital + pos_value
        ret = (final_value - self.initial_capital) / self.initial_capital * 100
        print(f"\n  最终资产: {final_value:,.0f}")
        print(f"  总收益率: {ret:+.2f}%")
        print(f"\n  文件:")
        print(f"  - 配置: {self.config_file}")
        print(f"  - 持仓配置: {self.position_file}")
        print(f"  - 持仓文件: {self.positions_file}")
        print(f"  - 交易文件: {self.trades_file}")

# ================================================
#                     主程序
# ================================================
if __name__ == "__main__":
    print("="*70)
    print("  全A股监控系统（完整配置版）")
    print("="*70)
    monitor = PersistentMarketMonitor(config_file='config.csv', position_file='position.py')
    monitor.run()
