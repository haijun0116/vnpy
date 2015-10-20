# encoding: UTF-8

import shelve
import MySQLdb

from eventEngine import *
from pymongo import  MongoClient as Connection
from pymongo.errors import *
from datetime import datetime, timedelta, time

from strategyEngine import *



########################################################################
class LimitOrder(object):
    """限价单对象"""

    #----------------------------------------------------------------------
    def __init__(self, symbol):
        """Constructor"""
        self.symbol = symbol             # 报单合约
        self.price = 0                   # 报单价格
        self.volume = 0                  # 报单合约数量
        self.direction = None            # 方向
        self.offset = None               # 开/平

        #Modified by Incense Lee
        self.orderTime = datetime.now()  # 下单时间


########################################################################
class BacktestingEngine(object):
    """
    回测引擎，作用：
    1. 从数据库中读取数据并回放
    2. 作为StrategyEngine创建时的参数传入
    """

    #----------------------------------------------------------------------
    def __init__(self):
        """Constructor"""
        self.eventEngine = EventEngine()  # 实例化
        
        # 策略引擎
        self.strategyEngine = None        # 通过setStrategyEngine进行设置

        # TICK历史数据列表，由于要使用For循环来实现仿真回放
        # 使用list的速度比Numpy和Pandas都要更快
        self.listDataHistory = []

        # 限价单字典
        self.dictOrder = {}
        
        # 最新的TICK数据
        self.currentData = None
        
        # 回测的成交字典
        self.listTrade = []
        
        # 报单编号
        self.orderRef = 0
        
        # 成交编号
        self.tradeID = 0

        # 回测编号
        self.Id = datetime.now().strftime('%Y%m%d-%H%M%S')
        
    #----------------------------------------------------------------------
    def setStrategyEngine(self, engine):
        """设置策略引擎"""
        self.strategyEngine = engine
        self.writeLog(u'策略引擎设置完成')
    
    #----------------------------------------------------------------------
    def connectMongo(self):
        """连接MongoDB数据库"""
        try:
            self.__mongoConnection = Connection()
            self.__mongoConnected = True
            self.__mongoTickDB = self.__mongoConnection['TickDB']
            self.writeLog(u'回测引擎连接MongoDB成功')
        except ConnectionFailure:
            self.writeLog(u'回测引擎连接MongoDB失败')


    #----------------------------------------------------------------------
    def loadMongoDataHistory(self, symbol, startDate, endDate):
        """从Mongo载入历史TICK数据"""
        if self.__mongoConnected:
            collection = self.__mongoTickDB[symbol]
            
            # 如果输入了读取TICK的最后日期
            if endDate:
                cx = collection.find({'date':{'$gte':startDate, '$lte':endDate}})
            elif startDate:
                cx = collection.find({'date':{'$gte':startDate}})
            else:
                cx = collection.find()
            
            # 将TICK数据读入内存
            self.listDataHistory = [data for data in cx]
            
            self.writeLog(u'历史TICK数据载入完成')
        else:
            self.writeLog(u'MongoDB未连接，请检查')


    #----------------------------------------------------------------------
    def connectMysql(self):
        """连接MysqlDB"""
        try:
            self.__mysqlConnection = MySQLdb.connect(host='vnpy.cloudapp.net', user='stockcn',
                                                     passwd='7uhb*IJN', db='stockcn', port=3306)
            self.__mysqlConnected = True
            self.writeLog(u'回测引擎连接MysqlDB成功')
        except ConnectionFailure:
            self.writeLog(u'回测引擎连接MysqlDB失败')
    #----------------------------------------------------------------------
    def loadMysqlDataHistory(self, symbol, startDate, endDate):
        """从Mysql载入历史TICK数据,"""
        #Todo :判断开始和结束时间，如果间隔天过长，数据量会过大，需要批次提取。
        try:

            if self.__mysqlConnected:

                #获取指针
                cur = self.__mysqlConnection.cursor(MySQLdb.cursors.DictCursor)

                if endDate:

                   sqlstring = ' select \'{0}\' as InstrumentID, str_to_date(concat(ndate,\' \', ntime),' \
                               '\'%Y-%m-%d %H:%i:%s\') as UpdateTime,price as LastPrice,vol as Volume,' \
                               'position_vol as OpenInterest,bid1_price as BidPrice1,bid1_vol as BidVolume1, ' \
                               'sell1_price as AskPrice1, sell1_vol as AskVolume1 from TB_{0}MI ' \
                               'where ndate between cast(\'{1}\' as date) and cast(\'{2}\' as date)'.format(symbol,  startDate, endDate)

                elif startDate:

                   sqlstring = ' select \'{0}\' as InstrumentID,str_to_date(concat(ndate,\' \', ntime),' \
                               '\'%Y-%m-%d %H:%i:%s\') as UpdateTime,price as LastPrice,vol as Volume,' \
                               'position_vol as OpenInterest,bid1_price as BidPrice1,bid1_vol as BidVolume1, ' \
                               'sell1_price as AskPrice1, sell1_vol as AskVolume1 from TB__{0}MI ' \
                               'where ndate > cast(\'{1}\' as date)'.format( symbol, startDate)

                else:

                   sqlstring =' select \'{0}\' as InstrumentID,str_to_date(concat(ndate,\' \', ntime),' \
                              '\'%Y-%m-%d %H:%i:%s\') as UpdateTime,price as LastPrice,vol as Volume,' \
                              'position_vol as OpenInterest,bid1_price as BidPrice1,bid1_vol as BidVolume1, ' \
                              'sell1_price as AskPrice1, sell1_vol as AskVolume1 from TB__{0}MI '.format(symbol)

                self.writeLog(sqlstring)

                count = cur.execute(sqlstring)
                self.writeLog(u'历史TICK数据共{0}条'.format(count))

                # 将TICK数据读入内存
                #self.listDataHistory = cur.fetchall()

                fetch_counts = 0
                fetch_size = 1000

                while True:
                    results = cur.fetchmany(fetch_size)

                    if not results:
                        break

                    fetch_counts = fetch_counts+fetch_size

                    if not self.listDataHistory:

                        self.listDataHistory =results

                    else:
                        self.listDataHistory =  self.listDataHistory + results

                    self.writeLog(u'历史TICK数据载入{0}条'.format(fetch_counts))

                self.writeLog(u'历史TICK数据载入完成，{1}~{2},共{0}条'.format(count,startDate,endDate))

            else:
                self.writeLog(u'MysqlDB未连接，请检查')
        except MySQLdb.Error, e:
            self.writeLog(u'MysqlDB载入数据失败，请检查.Error {0}'.format(e))

    #----------------------------------------------------------------------
    def getMysqlDeltaDate(self,symbol, startDate, decreaseDays):
        """从mysql库中获取交易日前若干天"""
        try:
            if self.__mysqlConnected:

                #获取指针
                cur = self.__mysqlConnection.cursor()

                sqlstring='select distinct ndate from TB_{0}MI where ndate < ' \
                          'cast(\'{1}\' as date) order by ndate desc limit {2},1'.format(symbol, startDate, decreaseDays-1)

                self.writeLog(sqlstring)

                count = cur.execute(sqlstring)

                if count > 0:

                    result = cur.fetchone()

                    return result[0]

                else:
                    self.writeLog(u'MysqlDB没有查询结果，请检查日期')

            else:
                self.writeLog(u'MysqlDB未连接，请检查')

        except MySQLdb.Error, e:
            self.writeLog(u'MysqlDB载入数据失败，请检查.Error {0}: {1}'.format(e.arg[0],e.arg[1]))

        td = timedelta(days=3)

        return startDate-td;

    #----------------------------------------------------------------------
    def processLimitOrder(self):
        """
        处理限价单
        为体现准确性，回测引擎需要真实tick数据的买一或卖一价比对。
        """
        for ref, order in self.dictOrder.items():
            # 如果是买单，且限价大于等于当前TICK的卖一价，则假设成交
            if order.direction == DIRECTION_BUY and \
               order.price >= self.currentData['AskPrice1']:
                self.executeLimitOrder(ref, order, self.currentData['AskPrice1'])
            # 如果是卖单，且限价低于当前TICK的买一价，则假设全部成交
            if order.direction == DIRECTION_SELL and \
               order.price <= self.currentData['BidPrice1']:
                self.executeLimitOrder(ref, order, self.currentData['BidPrice1'])
    
    #----------------------------------------------------------------------
    def executeLimitOrder(self, ref, order, price):
        """
        模拟限价单成交处理
        回测引擎模拟成交
        """
        # 成交回报
        self.tradeID = self.tradeID + 1
        
        tradeData = {}
        tradeData['InstrumentID'] = order.symbol
        tradeData['OrderRef'] = ref
        tradeData['TradeID'] = str(self.tradeID)
        tradeData['Direction'] = order.direction
        tradeData['OffsetFlag'] = order.offset
        tradeData['Price'] = price
        tradeData['Volume'] = order.volume
        tradeData['TradeTime'] = order.orderTime

        print tradeData

        tradeEvent = Event()
        tradeEvent.dict_['data'] = tradeData
        self.strategyEngine.updateTrade(tradeEvent)
        
        # 报单回报
        orderData = {}
        orderData['InstrumentID'] = order.symbol
        orderData['OrderRef'] = ref
        orderData['Direction'] = order.direction
        orderData['CombOffsetFlag'] = order.offset
        orderData['LimitPrice'] = price
        orderData['VolumeTotalOriginal'] = order.volume
        orderData['VolumeTraded'] = order.volume
        orderData['InsertTime'] = order.orderTime
        orderData['CancelTime'] = ''
        orderData['FrontID'] = ''
        orderData['SessionID'] = ''
        orderData['OrderStatus'] = ''
        
        orderEvent = Event()
        orderEvent.dict_['data'] = orderData
        self.strategyEngine.updateOrder(orderEvent)

        # 记录该成交到列表中
        self.listTrade.append(tradeData)

        # 删除该限价单
        del self.dictOrder[ref]
                
    #----------------------------------------------------------------------
    def startBacktesting(self):
        """开始回测"""

        ISOTIMEFORMAT = '%Y-%m-%d %X'

        t1 = datetime.now()

        self.writeLog(u'开始回测,{0}'.format(str(t1 )))

        for data in self.listDataHistory:


            # 记录最新的TICK数据
            self.currentData = data

            # 处理限价单
            self.processLimitOrder()

            # 推送到策略引擎中
            event = Event()
            event.dict_['data'] = data
            self.strategyEngine.updateMarketData(event)

        # 保存交易到数据库中
        self.saveTradeDataToMysql()


        t2 = datetime.now()

        self.writeLog(u'回测结束,{0},耗时:{1}秒'.format(str(t2),(t2-t1).seconds))

        # 保存策略过程数据到数据库
        self.strategyEngine.saveData(self.Id)


    
    #----------------------------------------------------------------------
    def sendOrder(self, instrumentid, exchangeid, price, pricetype, volume, direction, offset, orderTime=datetime.now()):
        """回测发单"""
        order = LimitOrder(instrumentid)        # 限价报单
        order.price = price                     # 报单价格
        order.direction = direction             # 买卖方向
        order.volume = volume                   # 报单数量
        order.offset = offset
        order.orderTime = orderTime             # 报单时间


        self.orderRef = self.orderRef + 1       # 报单编号

        self.dictOrder[str(self.orderRef)] = order

        return str(self.orderRef)
    
    #----------------------------------------------------------------------
    def cancelOrder(self, instrumentid, exchangeid, orderref, frontid, sessionid):
        """回测撤单"""
        try:
            del self.dictOrder[orderref]
        except KeyError:
            pass
        
    #----------------------------------------------------------------------
    def writeLog(self, log):
        """写日志"""
        print log


    #----------------------------------------------------------------------
    def subscribe(self, symbol, exchange):
        """仿真订阅合约"""
        pass

    #----------------------------------------------------------------------
    def selectInstrument(self, symbol):
        """读取合约数据"""
        d = {}
        d['ExchangeID'] = 'BackTesting'
        return d
    
    #----------------------------------------------------------------------
    def saveTradeData(self):
        """保存交易记录"""
        f = shelve.open('result.vn')
        f['listTrade'] = self.listTrade
        f.close()
        """仿真订阅合约"""
        pass

    #----------------------------------------------------------------------
    def saveTradeDataToMysql(self):
        """保存交易记录到mysql,added by Incense Lee"""
        if self.__mysqlConnected:
            sql='insert into BackTest.TB_Trade (Id,symbol,orderRef,tradeID,direction,offset,price,volume,tradeTime) values '
            values = ''

            print u'共{0}条交易记录.'.format(len(self.listTrade))

            if len(self.listTrade) == 0:
                return

            for tradeItem in self.listTrade:

                if len(values) > 0:
                    values = values + ','

                if tradeItem['OffsetFlag'] == '0':
                    amount = 0-float(tradeItem['Price'])*int(tradeItem['Volume'])
                else:
                    amount = float(tradeItem['Price'])*int(tradeItem['Volume'])


                values = values + '(\'{0}\',\'{1}\',{2},{3},{4},{5},{6},{7},\'{8}\',{9})'.format(
                    self.Id,
                    tradeItem['InstrumentID'],
                    tradeItem['OrderRef'],
                    tradeItem['TradeID'],
                    tradeItem['Direction'],
                    tradeItem['OffsetFlag'],
                    tradeItem['Price'],
                    tradeItem['Volume'],
                    tradeItem['TradeTime'].strftime('%Y-%m-%d %H:%M:%S'),amount)

            cur = self.__mysqlConnection.cursor(MySQLdb.cursors.DictCursor)


            try:
                cur.execute(sql+values)
                self.__mysqlConnection.commit()
            except Exception, e:
                print e

        else:
            self.saveTradeData()

