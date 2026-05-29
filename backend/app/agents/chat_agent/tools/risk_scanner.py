import os
import math
import re

from app.agents.chat_agent.schemas import ScenarioId, Signal, SignalScanResult

try:
    import pandas as pd
except ImportError:  # pandas is only required for the optional batch CLI path.
    pd = None

CSV_PATH = os.environ.get("CSV_PATH", r".\data\input\raw_news.csv")
OUT_PATH = os.environ.get("OUT_PATH", r".\reports\predictions\risk_labeler_v3_output.csv")

# ---------------- 基础抽取 ----------------
PCT_RE = re.compile(r'([+-]?\d+(?:\.\d+)?)\s*%')
AMT_RE = re.compile(
    r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?|\d+)\s*'
    r'(亿美元|亿美金|千万美元|百万美元|万美元|万USDT|万USDC|万美金|美元|USDT|USDC)',
    re.IGNORECASE
)

TIME_HINTS = ["分钟", "小时", "日内", "短时间", "瞬间", "盘中", "24小时", "24h", "今晨", "今日", "当天"]

# ---------------- 全局排除 / 缓和语义 ----------------
NEG_FRAUD = ["反欺诈", "防欺诈", "反诈骗宣传", "欺诈检测", "反洗钱", "AML", "合规体系", "风控系统"]
NEG_REG_ONLY_TALK = ["呼吁", "建议", "提议", "敦促", "讨论", "区分", "澄清", "拟", "草案", "征求意见"]
NEG_TICKER_COLLISION = ["BTC原油", "原油出口", "杰伊汉港", "阿塞拜疆"]

NEG_NO_RISK = [
    "不涉及安全事件", "未涉及安全事件", "无安全事件",
    "不涉及资产异常", "未涉及资产异常",
    "不涉及资产安全", "未涉及资产安全",
    "不影响用户资产", "用户资金未受影响", "未造成资金损失",
    "无资金损失", "未造成损失", "已修复", "完成修复",
    "已恢复", "恢复正常", "误报", "并非攻击", "并非被盗",
    "不存在被盗风险", "并不存在被盗风险", "并非漏洞",
    "并非安全事故", "非安全事故",
    "安全运营", "平安", "安全无虞", "未受影响", "安然无恙"
]

NEG_PLANNED_MAINT = [
    "例行维护", "计划内维护", "系统升级", "例行升级",
    "例行系统升级", "按计划推进", "常规维护"
]

NEG_INTERNAL_TRANSFER = [
    "内部调拨", "内部转移", "冷钱包内部调拨", "钱包归集",
    "资金归集", "地址归集", "热钱包迁移", "冷钱包迁移",
    "官方钱包迁移"
]

NEG_POSITIVE_MOVE = ["小幅上涨", "微涨", "温和上涨", "企稳回升", "慢牛", "持续走高", "反弹", "回升", "上涨", "涨幅收窄", "回暖", "普涨", "板块轮动", "领涨"]
NEG_STAT_DESC = ["平均", "均值", "中位数", "标准差", "方差", "统计", "概率", "分布", "回归", "相关性"]
NEG_VOL_FORECAST = ["预测", "调查", "预期", "有望", "预计", "展望", "分析报告", "或将", "可能", "可能将", "预判"]

# 链上/加密领域限定词
CRYPTO_DOMAIN = ["链上", "智能合约", "DeFi", "defi", "代币", "token", "Token", "TOKEN", "合约地址", "私钥", "钱包", "跨链", "预言机", "DApp", "dApp", "NFT", "nft", "矿工", "区块", "交易哈希", "gas", "GAS", "Gas", "比特币", "以太坊", "加密货币", "数字资产", "虚拟货币", "币"]

# score_hack 非加密领域否定词
NEG_NON_CRYPTO_HACK = ["医疗机构", "医疗数据", "AI", "人工智能", "软件", "企业网络", "网络安全", "数据泄露", "黑客松", "hackathon", "Hackathon", "IT系统", "传统企业", "工业控制系统"]

# score_hack 否定语境（已修复/无损失等）改为减权列表，不再完全阻断
NEG_HACK_DOWNWEIGHT = ["追回", "已修复", "完成修复", "报告漏洞", "漏洞赏金", "不受影响", "未受影响", "安然无恙",
                       "无资产损失", "未造成损失", "无资金损失", "已经恢复", "误报", "用户资金未受影响",
                       "不涉及用户资产", "未影响用户", "资金安全"]

# score_hack 防御/澄清/防范语境——出现时分数上限0.3
NEG_HACK_MITIGATION = ["冻结", "防范", "不受影响", "不会用于", "不涉及", "未受影响", "未涉及", "否认", "澄清",
                       "安全措施", "防范措施", "保护措施", "防御", "不会遭", "不会受到", "未发现损失",
                       "安全运营", "平安", "安全无虞", "未受", "不会影响"]

# score_hack 商业/金融无关新闻排除（收购、信贷等非攻击事件）
NEG_HACK_BUSINESS_EXCLUDE = ["收购", "信贷基金", "私人信贷", "贷款协议", "发放贷款", "借贷协议"]

# score_hack 新增：历史/过去漏洞语境减权（但若提及损失则不触发）
NEG_HACK_PAST = ["之前漏洞", "此前漏洞", "过去的攻击", "曾遭攻击", "之前被黑", "历史漏洞"]

# score_hack 新增：漏洞报告/安全研究/审计类排除（若未提及实际损失则完全抑制）
NEG_VULN_REPORT = ["漏洞报告", "漏洞披露", "漏洞挖掘", "安全研究", "渗透测试", "漏洞复现", "漏洞分析",
                   "审计报告", "审计发现", "代码审计", "安全审计", "白帽", "漏洞赏金", "提交漏洞",
                   "安全公告", "安全提升", "安全合作", "共建安全", "白帽联合", "安全响应"]

# score_hack 新增：非攻击性质的企业/金融行为（避免误报）
NEG_HACK_NON_ATTACK = ["增持", "增持了", "买入", "购买", "建仓", "ATM 股票计划", "ATM 发行计划", "财库", "收益生成策略",
                       "理财合作", "利息", "存款", "储蓄", "投资组合", "资产管理", "战略投资",
                       "公司债券", "股票", "回购", "DeFi 收益", "收益池", "流动性挖矿"]

# score_hack 新增：强烈否定（安全运营/无损失等）——出现且无实际损失时直接返回0
NEG_HACK_STRONG_NO_RISK = ["无资金损失", "未造成损失", "安全运营", "平安无事", "安然无恙", "未受影响",
                           "安全无虞", "未遭攻击", "未发现损失", "一切正常", "正常运行"]

# score_hack v3 新增：安全产品/讨论/非攻击语境，直接阻断或强力降权
NEG_HACK_SAFETY = ["安全产品", "安全服务", "安全合作", "安全响应", "安全提升", "安全公告", "安全运营", "安全无虞",
                   "推出安全", "发布安全", "上线安全", "安全方案", "安全白皮书", "安全演练", "安全教育",
                   "漏洞研究", "安全研究", "渗透测试", "代码审计", "安全审核", "白帽",
                   "安全运营正常", "无资产损失", "成功抵御", "防御成功", "加固", "安全加固",
                   "安全团队", "安全测试", "安全演习", "安全态势", "安全架构"]
# score_hack v3 新增：产品/平台发布，不涉及攻击
NEG_HACK_PRODUCT_LAUNCH = ["推出", "上线", "发布", "启动", "新产品", "新功能", "平台升级", "版本发布"]

# score_hack 新增：通用漏洞关键词（合并原有 KW_HACK 并扩充）
KW_HACK_BASE = ["攻击", "被盗", "盗取", "重入", "闪电贷", "利用漏洞", "黑客", "exploit", "hacker", "入侵",
                "遭受攻击", "攻击事件", "攻破", "窃取", "损失金额", "被黑", "安全漏洞", "由于漏洞", "黑客攻击",
                "漏洞攻击", "社会工程", "钓鱼攻击", "量子攻击", "后门", "合约暂停", "安全事件", "异常活动",
                "坏账", "安全警钟", "社会工程攻击", "AI攻击", "热钱包被盗", "内部攻击", "凭证泄露",
                "内部热钱包被盗", "量子计算", "密钥恢复", "冻结地址", "截留资金", "漏洞", "资金被盗",
                "桥接被攻击", "冻结黑客地址", "窃取", "特权地址结留"]
KW_HACK_EXTRA = ["利用", "漏洞", "未授权铸造", "资金被盗", "桥接被攻击", "协议被利用", "合约缺陷", "重入漏洞",
                 "预言机攻击", "治理攻击", "私钥泄漏", "价格操纵", "女巫攻击", "51%攻击", "粉尘攻击",
                 "拒绝服务", "DoS", "DDoS", "交易回滚", "双花", "资金丢失", "冻结资产",
                 "非法铸造", "异常提款", "攻击合约", "智能合约漏洞", "闪电贷攻击", "社会工程攻击",
                 "量子攻击", "私钥恢复", "漏洞利用", "损失", "黑客", "入侵",
                 "严重漏洞", "冻结黑客地址", "攻击者地址", "无限期冻结", "用户资金冻结", "提款冻结漏洞",
                 "截留资金", "黑客地址"]
KW_HACK = list(set(KW_HACK_BASE + KW_HACK_EXTRA))

# 新增：漏洞高危关键词（无需攻击证据即可高分）
KW_VULN_HIGH = ["严重漏洞", "高危漏洞", "重大安全漏洞", "未授权铸造", "权限提升漏洞", "致命漏洞", "关键漏洞"]

# 新增：事后处理关键词，视为攻击事件衍生信号
KW_HACK_POST_EVENT = ["冻结黑客地址", "已冻结", "拦截资金", "阻止交易", "成功冻结", "冻结资产", "拦截黑客", "阻断攻击"]

# score_liquidation 否定词
NEG_LIQ_FALSE = ["交易量", "涨幅", "纳入指数", "成交量", "成交额", "交易额", "市值", "总市值", "流通市值"]
NEG_LIQ_PROTECT = ["降低清算风险", "避免清算", "清算保护", "防止爆仓", "降低爆仓风险", "规避清算", "清算预防", "抗清算"]
NEG_LIQ_LIQUIDITY_NON_RISK = ["代币化流动性", "流动性基金", "流动性产品", "清算价", "被动清算", "接近清算", "抵押品使用率", "未实现损失", "接近爆仓", "清算线附近"]

# score_liquidation 新增：讨论/策略类排除
NEG_LIQ_DISCUSSION = ["仓位策略", "仓位管理", "分享", "分析", "观点", "看法", "教程", "如果", "假设", "假如"]
# score_liquidation 新增：产品上线排除
NEG_LIQ_PRODUCT_LAUNCH = ["合约上市", "合约上线", "推出合约", "上线合约"]
# score_liquidation 新增：宏观领域过滤（防止与地缘新闻混淆）
NEG_LIQ_MACRO = ["石油", "能源", "原油", "霍尔木兹", "封锁", "地缘", "油运", "能源市场"]

# score_whale 否定词
NEG_WHALE_FALSE = ["融资", "市值", "交易量", "牌照", "总市值", "流通市值", "成交额", "交易额", "成交量",
                   "ETF", "ETF基金", "资产管理公司", "贝莱德", "富达", "灰度", "MicroStrategy", "上市公司",
                   "购入", "增持", "持仓", "净资产", "净值", "资产管理", "基金", "信托", "纳入指数",
                   "个人净资产", "亿万富翁", "富豪榜", "声称", "资产组合", "持仓披露", "持有声明", "持仓情况",
                   "赔偿", "退款", "受害者", "受害方"]

# score_whale 产品/平台推广类上下文，非真实转移
NEG_WHALE_PRODUCT_DESC = ["推出", "上线", "平台", "协议", "DeFi", "借贷", "流动性池", "AMM", "质押", "挖矿", "产品"]

# score_volatility 否定词（扩充财务利好）
NEG_VOL_FALSE = ["活跃地址", "交易量增长", "支持率", "网络活动", "用户增长", "开发者", "TVL", "tvl", "锁仓量",
                 "总市值", "24小时交易量", "占有率达", "占比", "市值排名", "交易量排名", "成交量排名", "市值报告",
                 "收入与利润", "利润增长", "营收增长", "业绩增长", "每股收益", "息税前利润", "财务报告", "业绩", "收益增长",
                 "创新高", "交易量创新高", "新高"]

# score_volatility 非市场内容否定词（访谈/观点/AI等）
NEG_VOL_NON_MARKET = ["访谈", "AMA", "分析师指出", "分析师表示", "分析师认为", "观点", "建议", "学习",
                      "人工智能", "AI趋势", "科普", "教育", "指南", "入门", "初学者"]

# score_volatility 新增：中性行为词，不能作为异常波动证据
NEG_VOL_NEUTRAL = ["持仓变动", "解锁代币", "解锁", "代币解锁", "投资于", "买入", "卖出", "增持", "减持", "定投",
                   "长期持有", "持有", "战略投资", "配置于", "纳入投资组合", "资产配置"]

# score_volatility 新增：技术分析术语排除
NEG_VOL_TECH = ["金叉", "死叉", "MACD", "RSI", "布林带", "均线", "支撑位", "阻力位", "技术指标", "斐波那契"]

# score_volatility v3.1 日常行情短语抑制
NEG_VOL_DAILY = ["板块上涨", "板块下跌", "涨跌互现", "小幅上涨", "小幅下跌", "微涨", "微跌",
                 "震荡行情", "横盘", "窄幅波动", "技术性反弹", "回调", "修正", "盘整",
                 "行情回顾", "市场总结", "日报", "周报", "快报"]

# score_volatility 新增：主流币种/市场整体要求（用于区分系统风险与个股）
MAJOR_MARKET_TOKENS = ["BTC", "比特币", "ETH", "以太坊", "主流币", "大盘", "整体市场", "市场全线", "币市", "加密市场", "总市值", "系统风险"]

# score_regulatory 否定词
NEG_REG_FALSE = ["AI", "人工智能", "谷歌", "医疗", "身份验证", "生物识别", "自动驾驶"]
NEG_REGULATORY_POSITIVE = ["解除禁令", "解除制裁", "允许", "不视为", "不构成", "裁定", "不属于证券",
                           "许可", "合法化", "认可", "放行", "批准", "放宽", "放松",
                           "监管明确", "合规指引", "监管框架", "监管沙盒", "试点", "豁免",
                           "胜诉", "驳回", "否决", "撤销指控", "不受影响", "法院驳回"]

# score_regulatory 新增：中性/推进性表述排除
NEG_REGULATORY_NEUTRAL = ["推动监管", "寻求监管", "监管进展", "公众咨询", "框架", "指引", "试点", "建议监管", "监管沙盒", "合规指引"]

# score_regulatory 新增：否定/缓和词（质疑、反对、假设、无计划等）
NEG_REGULATORY_DISCUSS = ["质疑", "反对", "不会影响", "不采取行动", "申请不采取行动", "不影响", "无影响", "未受", "不会",
                          "不予", "否认", "辩驳", "驳斥", "不太可能", "没有计划", "并不意味", "无需", "讨论", "评论", "看法",
                          "表示", "声称", "认为", "分析", "推测"]

# 负面执法动作词（用于 score_regulatory）—— 强负面
REG_STRONG_NEGATIVE = ["罚款", "指控", "起诉", "逮捕", "禁令", "禁止", "冻结", "查封", "判刑", "监禁", "处罚", "制裁", "宣判", "裁决"]
# 中等负面/弱信号
REG_MODERATE_SIGNALS = ["调查", "审查", "警告", "批评", "听证会", "关注", "担忧", "压力", "监管阻力", "国会批评", "监管调查"]
# 立法/政策讨论
REG_WEAK_SIGNALS = ["提案", "草案", "咨询期", "立法", "法规", "政策", "法案", "呼吁", "反对", "合规", "KYC", "反洗钱", "监管框架", "监管进展", "公众咨询"]

# score_regulatory 加密领域限定词
REG_CRYPTO_DOMAIN = ["加密", "数字货币", "虚拟货币", "代币", "token", "Token", "TOKEN", "区块链", "比特币", "以太坊", "稳定币", "交易所", "DeFi", "defi", "NFT", "nft"]

# score_fraud 额外关键词
KW_FRAUD_EXTRA = ["团队控制", "供应量集中", "内部人士", "钱包持有", "代币集中", "筹码集中", "高度控盘", "操纵市场"]

# score_fraud 事后降权词
FRAUD_POST_EVENT = ["赔偿申请", "追回资金", "警方", "逮捕", "判决", "法庭", "量刑", "侦破", "破获"]

# score_volatility 漏召回关键词（扩充）
KW_VOL_MISS = ["价格波动", "最大痛苦点", "抛售", "回调", "挤压", "逼空", "空头挤压", "多头挤压",
               "价格下调", "大幅下挫", "跳水", "滑落", "急跌", "大跌", "狂跌", "熔断",
               "期权到期", "挤仓", "轧空", "信任危机", "阻力崩溃", "暴力拉升", "暴力下跌",
               "回落至", "恐慌性", "支撑缺失", "升级态势", "情绪波动", "市场动荡", "巨幅震荡",
               "价格回调", "急剧下跌", "急剧上涨", "一夜暴跌", "日内重挫"]

# score_volatility v3 新增：强异常信号词（直接认可高风险）
KW_VOL_STRONG_SIGNAL = ["闪崩", "插针", "瀑布", "腰斩", "暴跌", "恐慌抛售", "恐慌性抛售", "极度恐慌", "流动性枯竭", "瞬间暴跌", "瞬间拉升", "崩盘"]

# score_macro 拆分：强冲击信号 vs 弱宏观背景
KW_MACRO_STRONG = ["危机", "冲击", "战争", "军事行动", "紧张局势", "冲突", "制裁", "暴雷", "金融风暴", "崩溃",
                   "地缘冲突", "封锁", "停火", "地缘政治", "霍尔木兹", "海峡", "原油危机", "石油危机"]
KW_MACRO_WEAK = ["美元走强", "美元指数走强", "油价飙升", "美债收益率走高", "加息预期", "风险偏好下降", "避险情绪升温",
                 "通胀", "贬值", "资本管制", "贸易摩擦", "利率决议", "衰退", "经济衰退", "货币政策",
                 "原油", "石油", "能源危机"]

# score_macro 否定词（期望/概率削弱）
NEG_MACRO_FORECAST = ["预期", "概率", "预计", "不太可能", "可能将", "预测"]

# score_macro 新增：纯评论/观点排除
NEG_MACRO_COMMENT = ["分析", "评论", "AMA", "讲话", "采访", "访谈", "观点", "报告", "展望", "讨论", "知乎", "交流",
                     "认为", "声称", "分析称", "研究称", "推测", "预计", "书评", "发言", "对话", "嘉年华",
                     "播客", "在播客中", "专栏", "署名文章"]

# score_macro 新增：利好方向词（缓解、停火、开放等），出现时大幅降权
NEG_MACRO_POSITIVE = ["缓解", "停火", "开放", "支撑反弹", "上涨推动", "推动反弹", "支持市场", "协议达成",
                      "关系缓和", "解禁", "解除封锁", "恢复出口"]

# score_macro 加密市场关联词
MACRO_CRYPTO_LINK = ["加密市场", "比特币价格", "数字货币市场", "加密货币", "币价", "比特币", "以太坊", "主流币", "山寨币", "交易所",
                     "币市", "数字资产市场", "加密领域"]

# score_solvency 新增：非危机中性讨论排除
NEG_SOLVENCY_NON_CRISIS = ["代币化", "资产支持代币", "增持", "持仓", "买入", "资产管理", "收益策略", "代币化流动性", "资产代币化"]


USD_UNIT_MULT = {
    "美元": 1.0,
    "美金": 1.0,
    "USDT": 1.0,
    "USDC": 1.0,
    "万美元": 1e4,
    "万USDT": 1e4,
    "万USDC": 1e4,
    "万美金": 1e4,
    "百万美元": 1e6,
    "千万美元": 1e7,
    "亿美元": 1e8,
    "亿美金": 1e8,
}


def has_any(text, kws):
    t = (text or "")
    return any(k in t for k in kws)


def extract_max_pct(text):
    mx = 0.0
    for m in PCT_RE.finditer(text or ""):
        try:
            mx = max(mx, abs(float(m.group(1))))
        except Exception:
            pass
    return mx


def extract_usd_equiv(text):
    usd = 0.0
    for m in AMT_RE.finditer(text or ""):
        raw, unit = m.group(1), m.group(2)
        raw = raw.replace(",", "")
        try:
            val = float(raw)
        except Exception:
            continue
        u = unit.upper()
        usd += val * USD_UNIT_MULT.get(u, 0.0)
    return usd


def clip01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else float(x))


def smooth_strength(x, x0, scale):
    if x <= x0:
        return 0.0
    return 1.0 - math.exp(-(x - x0) / scale)


# ---------------- 风险打分 ----------------

# 1) 合约/链上漏洞攻击 (v3.1 强化安全语境抑制，提升漏洞与事后处理信号)
def score_hack(text):
    # 强烈否定词（安全运营、无任何损失）且无实际损失描述，直接返回0
    if has_any(text, NEG_HACK_STRONG_NO_RISK) and not has_any(text, ["损失", "被盗", "盗取", "资金丢失", "资金消失", "仍受损"]):
        return 0.0

    # v3.1 安全语境硬上限：若命中安全产品/研究/合作等词，且无真实损失证据，限制得分上限
    in_safety_context = has_any(text, NEG_HACK_SAFETY) or has_any(text, NEG_VULN_REPORT)
    has_real_loss = has_any(text, ["资金损失", "实际损失", "被盗", "盗取", "损失金额", "资金丢失", "用户资产受损"])

    # 安全语境下，若无真实损失，上限 0.2；若真实损失存在，上限 0.35
    if in_safety_context:
        if not has_real_loss:
            upper_bound = 0.2
        else:
            upper_bound = 0.35
        # 如果完全没有攻击证据，直接返回0
        if not has_any(text, ["攻击事件", "被黑", "利用漏洞", "黑客攻击", "漏洞攻击", "遭受攻击", "窃取", "被盗"]):
            return 0.0
        # 否则进入后续打分，但用上限限制
    else:
        upper_bound = 1.0

    # 非攻击商业/金融行为直接排除（增持、购买等），除非有攻击证据
    if has_any(text, NEG_HACK_NON_ATTACK) and not has_any(text, ["漏洞", "攻击", "被黑", "安全事件", "黑客"]):
        return 0.0

    # 商业无关新闻排除，除非存在明确攻击动作
    if has_any(text, NEG_HACK_BUSINESS_EXCLUDE) and not has_any(text, ["漏洞", "攻击", "被黑", "安全事件"]):
        return 0.0

    # 历史/过去语境：若无损失字眼，返回0
    if has_any(text, NEG_HACK_PAST) and not has_any(text, ["损失", "被盗", "盗取", "资金消失", "资金损失", "攻击事件"]):
        return 0.0

    # 若非加密领域且无加密域词，果断排除
    if has_any(text, NEG_NON_CRYPTO_HACK) and not has_any(text, CRYPTO_DOMAIN):
        return 0.0

    # 防御/澄清类语境，若无损失证据，强设上限0.3
    mitigated = has_any(text, NEG_HACK_MITIGATION)

    # 触发关键词
    if has_any(text, KW_HACK):
        usd = extract_usd_equiv(text)
        downweight = has_any(text, NEG_HACK_DOWNWEIGHT)
        has_loss_evid = has_any(text, ["损失", "被盗", "盗取", "资金消失", "资金损失", "被利用", "资金丢失", "仍受损", "未被追回"])
        has_attack_evid = has_any(text, ["攻击事件", "被黑", "安全漏洞", "利用漏洞", "黑客攻击", "漏洞攻击", "遭受攻击", "窃取",
                                         "利用", "漏洞", "未授权铸造", "资金被盗", "桥接被攻击", "攻击合约", "社会工程", "量子攻击",
                                         "量子计算", "冻结黑客地址", "截留资金"])

        # 高位漏洞关键词（严重漏洞等）：即使无攻击证据，也给较高分
        if has_any(text, KW_VULN_HIGH):
            score_val = 0.55
            if has_real_loss:
                score_val += 0.15
            if mitigated:
                score_val = min(score_val, 0.4)
            return min(score_val, upper_bound)

        # 事后处理关键词（冻结黑客地址等）：视为攻击相关信号
        if has_any(text, KW_HACK_POST_EVENT):
            score_val = 0.45
            if has_real_loss or usd > 0:
                score_val = 0.55
            if mitigated:
                score_val = min(score_val, 0.35)
            return min(score_val, upper_bound)

        # 防御语境，若无损失证据，分数最高0.3
        if mitigated and not has_loss_evid:
            return min(0.3, 0.15 if downweight else 0.25)

        # 有金额损失时大幅加成
        if usd > 0:
            base = 0.85
            score_val = clip01(base + 0.10 * smooth_strength(usd, 1_000_000, 50_000_000))
            if downweight:
                score_val = max(0.35, score_val * 0.5)
            if mitigated:
                score_val = min(score_val, 0.4)
            score_val = max(score_val, 0.6)
            return min(score_val, upper_bound)

        # 明确攻击证据
        if has_attack_evid:
            if downweight and not has_loss_evid:
                base = 0.3
            elif has_loss_evid:
                base = 0.65
            else:
                base = 0.45
            if mitigated:
                base = min(base, 0.35)
            return min(base, upper_bound)

        # 有损失描述但无攻击证据
        if has_loss_evid:
            base = 0.6
            if downweight:
                base = 0.4
            if mitigated:
                base = min(base, 0.4)
            return min(max(base, 0.35), upper_bound)

        # 仅有攻击关键词但既无损失也无强攻击词
        base = 0.25
        if downweight:
            base = 0.15
        if mitigated:
            base = min(base, 0.25)
        return min(base, upper_bound)
    return 0.0


# 2) 诈骗/跑路/rug (保持)
KW_FRAUD = ["诈骗", "骗局", "庞氏", "传销", "跑路", "rug", "rugpull", "钓鱼", "假冒", "冒充", "卷款"]


def score_fraud(text):
    if has_any(text, NEG_FRAUD):
        return 0.0
    if has_any(text, KW_FRAUD):
        if has_any(text, FRAUD_POST_EVENT):
            return 0.35
        return 0.88
    if has_any(text, KW_FRAUD_EXTRA):
        return 0.55
    return 0.0


# 3) 监管/法律风险 (v3.1 进一步降低讨论和中性的得分)
REG_ACTORS = ["SEC", "CFTC", "司法部", "检察", "法院", "监管", "执法", "警察", "法官", "审计", "调查机构", "税务",
              "央行", "中央银行", "联邦储备", "财政部长", "参议员", "众议员", "国会", "金融监管局", "FSB", "FCA"]

REG_WEAK_ACTIONS = ["申请不采取行动", "不采取行动函", "银行家协会质疑稳定币", "监管机构批准", "监管放行",
                    "合规许可", "牌照发放"]


def score_regulatory(text):
    if has_any(text, NEG_REG_FALSE):
        return 0.0

    # 纯讨论/提议语境，且无任何强负面行动，直接归零
    if has_any(text, NEG_REG_ONLY_TALK) and not has_any(text, REG_STRONG_NEGATIVE):
        return 0.0

    # 有利结果/驳回等，若无强负面行动，降为极低分
    if has_any(text, NEG_REGULATORY_POSITIVE):
        if not has_any(text, REG_STRONG_NEGATIVE):
            return 0.05
        return 0.20

    has_strong = has_any(text, REG_STRONG_NEGATIVE)
    discuss_discount = has_any(text, NEG_REGULATORY_DISCUSS)

    # 中性推动表述，且无强负面行动 — 直接给极低分
    if has_any(text, NEG_REGULATORY_NEUTRAL) and not has_strong:
        score_val = 0.02 if discuss_discount else 0.05
        return clip01(score_val)

    # 强负面执法动作 — 讨论折扣限制上限0.25
    if has_any(text, REG_ACTORS) and has_strong:
        base = 0.80
        if discuss_discount:
            base = min(base, 0.25)
        return base

    # 中等负面信号，加密领域下调
    has_crypto = has_any(text, REG_CRYPTO_DOMAIN)
    if has_any(text, REG_MODERATE_SIGNALS):
        if has_crypto:
            base = 0.18 if not discuss_discount else 0.08
        else:
            base = 0.10 if not discuss_discount else 0.05
        return clip01(base)

    # 弱信号/立法动态：无强负面时极低分
    has_reg_signal = has_any(text, REG_WEAK_SIGNALS) or has_any(text, ["监管", "政策", "法律"])
    if has_crypto and has_reg_signal:
        base = 0.08
        if discuss_discount:
            base = 0.03
        return clip01(base)
    if has_reg_signal:
        base = 0.03 if discuss_discount else 0.05
        return clip01(base)

    # 弱监管动作
    if has_crypto and has_any(text, REG_WEAK_ACTIONS):
        base = 0.10 if not discuss_discount else 0.04
        return clip01(base)

    # 通用监管关键词
    if has_any(text, ["法案", "草案", "国会批评", "监管阻力"]) and has_crypto:
        base = 0.08
        if discuss_discount:
            base = 0.03
        return clip01(base)

    return 0.0


# 4) 交易所/链/钱包运维风险 (保持)
KW_OUTAGE = ["暂停提现", "暂停充提", "暂停充值", "提现暂停", "充值暂停", "维护", "钱包维护", "宕机", "系统故障", "无法交易", "停止充提", "网络拥堵"]
KW_OUTAGE_EXTRA = ["冷钱包无法访问", "私钥未移交", "资产无法访问", "提款异常", "提现延迟", "充值延迟", "无法提现", "无法充值", "访问异常", "登录异常", "API异常"]


def score_outage(text):
    outage_keywords = KW_OUTAGE + KW_OUTAGE_EXTRA
    if not has_any(text, outage_keywords):
        return 0.0

    if has_any(text, NEG_PLANNED_MAINT) or has_any(text, NEG_NO_RISK):
        if "暂停提现" in text or "停止充提" in text or "暂停充提" in text:
            return 0.35
        return 0.20

    if has_any(text, ["暂停提现", "暂停充提", "停止充提", "提现暂停", "充值暂停", "无法提现", "无法充值"]):
        return 0.72

    if has_any(text, ["宕机", "系统故障", "无法交易"]):
        return 0.68

    if has_any(text, ["提现延迟", "充值延迟", "访问异常", "登录异常", "API异常"]):
        return 0.45

    return 0.55


# 5) 稳定币异常 (保持)
STABLES = ["USDT", "USDC", "DAI", "FDUSD", "TUSD", "UST", "USDD", "FRAX", "PYUSD", "稳定币"]
STABLE_HINTS = ["脱锚", "锚定", "锚离", "peg", "depeg", "跌破1美元", "跌破 1 美元", "回到1美元"]
STABLE_NUM = re.compile(r'\b0\.9\d\b|\b1\.0\d\b')


def score_stablecoin(text):
    if not has_any(text, STABLES):
        return 0.0
    if has_any(text, STABLE_HINTS) or STABLE_NUM.search(text or ""):
        return 0.85
    return 0.0


# 6) 清算/爆仓 (保持 v2.7)
KW_LIQ = ["爆仓", "强平", "清算", "liquidation", "强制平仓"]
KW_LIQ_WEAK = ["期权集中到期", "负资金费率", "空头挤压", "逼空", "清算风险", "爆仓风险", "强平风险", "清算压力"]
KW_LIQ_STRONG = ["清算强度", "清算金额", "将清算", "发生清算", "已清算", "实际清算"]


def score_liquidation(text):
    if has_any(text, NEG_LIQ_MACRO) and not has_any(text, ["爆仓", "强平", "已清算", "实际清算", "发生清算"]):
        return 0.0

    if has_any(text, NEG_LIQ_PROTECT):
        return 0.0
    if has_any(text, NEG_LIQ_FALSE):
        return 0.0

    if has_any(text, NEG_LIQ_DISCUSSION) and not has_any(text, ["爆仓", "强平", "已清算", "实际清算", "发生清算"]):
        return 0.0

    if has_any(text, NEG_LIQ_PRODUCT_LAUNCH) and not has_any(text, ["爆仓", "强平"]):
        return 0.0

    if has_any(text, NEG_LIQ_LIQUIDITY_NON_RISK):
        if has_any(text, KW_LIQ):
            return 0.15
        return 0.0

    has_strong_liq = has_any(text, KW_LIQ_STRONG)
    if has_any(text, KW_LIQ):
        usd = extract_usd_equiv(text)
        if usd > 0:
            if usd < 500_000:
                score_val = clip01(0.35 + 0.15 * smooth_strength(usd, 100_000, 500_000))
            elif usd < 5_000_000:
                score_val = clip01(0.45 + 0.20 * smooth_strength(usd, 500_000, 5_000_000))
            else:
                score_val = clip01(0.50 + 0.30 * smooth_strength(usd, 5_000_000, 20_000_000))
            return min(score_val, 0.65)
        if has_strong_liq:
            return 0.55
        return 0.40
    if has_any(text, KW_LIQ_WEAK):
        return 0.12
    return 0.0


# 7) 大额转账/巨鲸 (v3.1 提升非行为触发敏感度，降低金额门槛，扩充关键词)
KW_WHALE = ["巨鲸", "whale", "转入", "转出", "转入交易所", "转出交易所", "从匿名地址", "从未知地址", "链上", "地址", "钱包转移", "大额转账",
            "准备出售", "抛售", "转移至交易所准备卖出", "大户准备卖出", "鲸鱼卖出", "大户", "巨鲸地址", "大额转移", "巨额转账",
            "巨额转移", "大额交易", "大额资金", "大额资产", "持仓变动", "大户头寸",
            "大额转入", "大额转出", "未知钱包", "unknown wallet", "大量抛售", "巨量抛售",
            "链上异动", "异常转账"]
KW_WHALE_BEHAVIOUR = ["准备出售", "抛售", "清仓", "接近清仓", "大量解锁", "巨量的卖单", "巨量的买单", "大户出售", "大额卖单", "代币解锁", "巨额解锁",
                       "巨鲸开仓", "大户开仓", "大户头寸", "准备减持", "出售", "减持", "鲸鱼减持", "仓位转移", "持仓转移",
                       "大型持有者准备出售", "鲸鱼持有", "持有者准备出售", "大额砸盘"]


def score_whale(text):
    if has_any(text, NEG_WHALE_FALSE):
        return 0.0

    position_discount = 1.0
    if has_any(text, ["开仓", "平仓", "多头", "空头", "仓位调整", "头寸", "杠杆", "止盈", "止损"]) and not has_any(text, KW_WHALE_BEHAVIOUR):
        position_discount = 0.4

    whale_keywords = KW_WHALE + KW_WHALE_BEHAVIOUR
    if not has_any(text, whale_keywords):
        return 0.0

    if not has_any(text, ["转入", "转出", "转移", "发送", "从地址", "链上", "地址", "巨鲸", "whale", "大户", "鲸鱼", "持仓变动"] + KW_WHALE_BEHAVIOUR):
        return 0.0

    if has_any(text, NEG_WHALE_PRODUCT_DESC) and not has_any(text, ["地址", "交易哈希", "txid", "TXID"]):
        return 0.0

    future_discount = 1.0
    if has_any(text, ["计划", "即将", "预期", "可能", "或将", "潜在", "准备"]) and not has_any(text, ["已经", "已", "确认", "完成"]):
        future_discount = 0.3

    if has_any(text, NEG_INTERNAL_TRANSFER) or has_any(text, NEG_NO_RISK):
        usd = extract_usd_equiv(text)
        if usd > 50_000_000:
            return 0.10
        return 0.02

    usd = extract_usd_equiv(text)
    # 行为触发：基础分0.45，金额门槛1M
    if has_any(text, KW_WHALE_BEHAVIOUR):
        base = 0.45
        if usd > 1_000_000:
            base = clip01(0.45 + 0.15 * smooth_strength(usd, 1_000_000, 20_000_000))
        elif usd > 0:
            base = 0.35
        else:
            base = 0.28
        return base * future_discount * position_discount

    # 非行为触发：金额门槛降至1M，基础分提高至0.18，小于1M给予微弱分
    if usd < 1_000_000:
        return 0.05 * future_discount * position_discount
    # 1M以上逐步提分
    return clip01(0.18 + 0.25 * smooth_strength(usd, 1_000_000, 100_000_000)) * future_discount * position_discount


# 8) 行情异常波动 (v3.1 引入日常行情短语抑制，调整无百分比基础分)
KW_SHOCK = ["闪崩", "插针", "瀑布", "腰斩", "暴跌", "剧烈波动", "瞬间暴跌", "瞬间拉升"]


def score_volatility(text):
    # 必须与加密领域相关
    if not has_any(text, CRYPTO_DOMAIN):
        return 0.0

    # 日常行情短语抑制：若无暴跌等极端词，大幅降权
    if has_any(text, NEG_VOL_DAILY) and not has_any(text, KW_VOL_STRONG_SIGNAL + ["暴跌", "闪崩", "瀑布", "腰斩", "插针"]):
        return 0.0

    # 市场回顾/周报等，无极端词归零
    if has_any(text, ["市场回顾", "行情综述", "每日行情", "周报", "周评", "市场总结", "日报", "快报"]) and not has_any(text, KW_VOL_STRONG_SIGNAL + ["暴跌", "闪崩", "恐慌"]):
        return 0.0

    if has_any(text, NEG_VOL_NON_MARKET) and not has_any(text, KW_SHOCK + KW_VOL_MISS):
        return 0.0

    if has_any(text, NEG_VOL_NEUTRAL) and not has_any(text, KW_SHOCK + ["暴跌", "闪崩", "瀑布", "腰斩", "插针"]):
        return 0.0

    if has_any(text, ["收入与利润", "利润增长", "营收增长", "业绩增长", "每股收益", "息税前利润"]):
        if not has_any(text, ["暴跌", "闪崩", "瀑布", "腰斩", "插针", "危机", "暴雷"]):
            return 0.0

    if has_any(text, NEG_VOL_TECH) and not has_any(text, KW_SHOCK + ["暴跌", "闪崩"]):
        return 0.0

    if has_any(text, NEG_VOL_FORECAST) and not has_any(text, KW_SHOCK):
        return 0.0

    if has_any(text, NEG_VOL_FALSE):
        return 0.0

    pct = extract_max_pct(text)
    has_time = has_any(text, TIME_HINTS)
    has_softener = has_any(text, NEG_NO_RISK)

    if has_any(text, NEG_POSITIVE_MOVE) and not has_any(text, ["暴跌", "闪崩", "瀑布", "腰斩", "插针"] + KW_VOL_MISS + KW_SHOCK):
        return 0.0
    if has_any(text, NEG_STAT_DESC):
        return 0.0

    # 主流币种/市场整体性判断
    is_major = has_any(text, MAJOR_MARKET_TOKENS)
    major_factor = 1.0 if is_major else 0.3

    # 强波动信号独立高分
    if has_any(text, KW_VOL_STRONG_SIGNAL):
        base = 0.55 if has_softener else 0.70
        if has_time:
            base += 0.05
        score_val = clip01(base + 0.15 * smooth_strength(pct, 10, 20))
        return score_val * major_factor

    # 普通强波动关键词
    if has_any(text, KW_SHOCK):
        base = 0.50 if has_softener else 0.65
        if has_time:
            base += 0.05
        score_val = clip01(base + 0.20 * smooth_strength(pct, 15, 25))
        return score_val * major_factor

    # 漏召回关键词
    if has_any(text, KW_VOL_MISS):
        base = 0.40 if has_softener else 0.55
        if has_time:
            base += 0.05
        if pct > 0 or has_time:
            score_val = clip01(base + 0.15 * smooth_strength(pct, 10, 20))
        else:
            # 无百分比基础分降低至0.15（受日常抑制后实际更低）
            base = 0.15 if not has_softener else 0.10
            score_val = base
        return max(score_val * major_factor, 0.08)

    # 仅百分比触发
    if pct >= 50:
        base = 0.35 if has_softener else 0.45
        if has_time:
            base += 0.05
        score_val = clip01(base)
        return max(score_val * major_factor, 0.08)
    if pct >= 30:
        base = 0.20 if has_softener else 0.30
        if has_time:
            base += 0.05
        score_val = clip01(base + 0.50 * smooth_strength(pct, 30, 50))
        return max(score_val * major_factor, 0.08)
    if pct >= 25:
        base = 0.12 if has_softener else 0.18
        if has_time:
            base += 0.05
        score_val = clip01(base + 0.40 * smooth_strength(pct, 25, 45))
        return max(score_val * major_factor, 0.08)
    if pct >= 20:
        base = 0.08 if has_softener else 0.12
        if has_time:
            base += 0.05
        score_val = clip01(base + 0.30 * smooth_strength(pct, 20, 35))
        return max(score_val * major_factor, 0.08)
    if pct >= 15:
        base = 0.05 if has_softener else 0.10
        if has_time:
            base += 0.05
        score_val = clip01(base + 0.20 * smooth_strength(pct, 15, 25))
        return max(score_val * major_factor, 0.08)

    return 0.0


# 9) 项目治理 / 团队异常风险 (v3.1 扩充关键词，提升弱信号得分)
KW_TEAM = [
    "创始人失联", "团队失联", "删除社交媒体账号", "删除账号", "官网无法访问",
    "官网无法打开", "停止运营", "停更", "项目方失联", "团队突然解散",
    "官方失联", "核心成员离职", "多签异常", "治理攻击", "内部操纵",
    "创始人套现", "团队内讧", "核心成员被捕", "CEO离职", "CEO辞职",
    "联合创始人离开", "开发团队退出", "团队资金耗尽", "内部腐败", "项目方出货",
    "团队抛售", "项目方砸盘", "团队大量减持", "代币倾销", "退出骗局",
    "代币增发", "项目方减持", "多签异常", "合约销毁异常", "内部抛售",
    "团队解散", "控制权变更", "创始人被调查", "项目方跑路", "团队解体"
]
KW_TEAM_WEAK = ["高管离职", "项目停滞", "转型受阻", "团队变动", "人事调整", "治理争议", "投票率低", "提案失败", "人事震荡",
                "项目代币集中", "团队争议", "管理层震荡", "项目负责人离职"]


def score_team(text):
    if has_any(text, KW_TEAM):
        return 0.82
    if has_any(text, KW_TEAM_WEAK):
        return 0.45
    return 0.0


# 10) 偿付能力 / 储备 / 流动性风险 (v3.1 聚焦真实危机，排除中性金融行为)
KW_SOLV = [
    "偿付能力", "兑付", "挤兑", "储备不足", "储备透明度不足", "流动性危机",
    "流动性不足", "资不抵债", "现金流压力", "负债", "财务困境", "无法兑付",
    "抵押品使用率过高", "接近清算线", "未实现损失", "抵押品接近上限",
    "坏账", "准备金率", "无法提取", "暂停赎回", "赎回暂停", "资不抵债",
    "偿付危机", "储备金不足", "流动性枯竭", "资金缺口", "挤兑风险", "抵押品不足",
    "抵押池不足", "暂停提款", "无法偿还", "违约"
]


def score_solvency(text):
    # 排除代币化/增持等中性上下文，除非出现强危机词
    if has_any(text, NEG_SOLVENCY_NON_CRISIS):
        if not has_any(text, ["挤兑", "资不抵债", "储备不足", "无法提取", "违约", "偿付危机"]):
            return 0.0

    if has_any(text, KW_SOLV):
        if has_any(text, STABLES) or has_any(text, ["发行方", "储备资产"]):
            return 0.88
        return 0.78
    # 弱触发降低
    if has_any(text, ["流动性"]) and has_any(text, ["风险", "紧张", "不足", "危机", "压力"]):
        return 0.12
    if has_any(text, ["偿付", "偿债", "储备"]) and has_any(text, ["不足", "危机", "风险", "缺口"]):
        return 0.12
    return 0.0


# 11) 基础设施 / 协议层异常风险 (v3.1 扩充关键词，增加弱触发)
KW_INFRA = [
    "跨链桥异常", "跨链桥故障", "预言机异常", "预言机失灵", "停止出块",
    "分叉异常", "共识失败", "RPC故障", "节点故障", "主网故障", "网络停止",
    "网络中断", "共识问题", "分叉风险", "节点宕机", "出块停止", "链停止",
    "手续费异常", "手续费调至", "Gas费飙升", "预言机故障", "预言机价格异动",
    "区块重组", "分叉攻击", "共识攻击", "跨链桥暂停", "节点掉线", "主网暂停",
    "协议暂停", "智能合约暂停", "L2故障", "侧链故障", "预言机操纵", "Gas异常",
    "网络中断", "通信故障", "升级事故", "分叉争议",
    "网络分裂", "链上拥堵", "TPS暴跌", "验证者离线", "网络分区"
]

# 弱基础设施信号
KW_INFRA_WEAK = ["网络延迟", "Gas飙升", "节点响应慢", "状态不同步", "出块间隔延长", "交易未确认"]


def score_infra(text):
    if has_any(text, KW_INFRA):
        if has_any(text, NEG_NO_RISK):
            return 0.25
        return 0.75
    if has_any(text, KW_INFRA_WEAK):
        return 0.30
    return 0.0


# 12) 宏观 / 政策冲击风险 (v3.1 加强观点抑制，弱信号降级)
MACRO_ALL = KW_MACRO_STRONG + KW_MACRO_WEAK


def score_macro(text):
    if not has_any(text, MACRO_ALL):
        return 0.0
    # 纯评论/观点/预测文章，且非强冲击事件，直接排除
    if has_any(text, NEG_MACRO_COMMENT) and not has_any(text, KW_MACRO_STRONG):
        return 0.0
    # 必须与加密市场关联（强冲击可给低分）
    linked = has_any(text, MACRO_CRYPTO_LINK)
    strong = has_any(text, KW_MACRO_STRONG)
    has_positive = has_any(text, NEG_MACRO_POSITIVE)

    if not linked:
        if strong:
            if has_any(text, NEG_MACRO_COMMENT):
                return 0.0
            base = 0.20
            if has_any(text, NEG_MACRO_FORECAST):
                base *= 0.4
            if has_positive:
                base *= 0.2
            return clip01(base + 0.05 * smooth_strength(extract_max_pct(text), 5, 15))
        else:
            return 0.0

    # 有加密关联
    if has_any(text, NEG_MACRO_COMMENT) and not strong:
        return 0.0

    pct = extract_max_pct(text)
    has_forecast = has_any(text, NEG_MACRO_FORECAST)

    if strong:
        base = 0.50
        if has_forecast:
            base *= 0.4
        if has_positive:
            base *= 0.25
        return clip01(base + 0.10 * smooth_strength(pct, 3, 10))

    # 弱宏观信号上限降至0.15
    base = 0.15
    if has_forecast:
        base *= 0.30
    if has_positive:
        base *= 0.15
    score_val = clip01(base + 0.05 * smooth_strength(pct, 5, 15))
    return min(score_val, 0.15)


# ---------------- 风险配置 ----------------
RISK_SCORERS = {
    "score_hack": score_hack,
    "score_fraud": score_fraud,
    "score_regulatory": score_regulatory,
    "score_outage": score_outage,
    "score_stablecoin": score_stablecoin,
    "score_liquidation": score_liquidation,
    "score_whale": score_whale,
    "score_volatility": score_volatility,
    "score_team": score_team,
    "score_solvency": score_solvency,
    "score_infra": score_infra,
    "score_macro": score_macro,
}

RISK_NAME_MAP = {
    "score_hack": "链上漏洞 / 攻击风险",
    "score_fraud": "诈骗 / 跑路 / Rug Pull 风险",
    "score_regulatory": "监管与法律风险",
    "score_outage": "交易所与系统运维风险",
    "score_stablecoin": "稳定币异常风险",
    "score_liquidation": "爆仓 / 清算风险",
    "score_whale": "大额转账 / 巨鲸行为风险",
    "score_volatility": "异常行情波动风险",
    "score_team": "项目治理 / 团队异常风险",
    "score_solvency": "偿付能力 / 储备 / 流动性风险",
    "score_infra": "基础设施 / 协议层异常风险",
    "score_macro": "宏观 / 政策冲击风险",
}

RISK_SCENARIO_MAP: dict[str, ScenarioId] = {
    "score_hack": "S1_ATTACK_EXPLOIT",
    "score_fraud": "S7_FRAUD_GOVERNANCE",
    "score_outage": "S2_EXCHANGE_ABNORMALITY",
    "score_stablecoin": "S3_STABLECOIN_RESERVE",
    "score_solvency": "S3_STABLECOIN_RESERVE",
    "score_team": "S7_FRAUD_GOVERNANCE",
    "score_infra": "S4_INFRASTRUCTURE_FAILURE",
    "score_whale": "S8_WHALE_ONCHAIN_FLOW",
    "score_volatility": "S6_MARKET_LIQUIDATION",
    "score_macro": "S0_GENERAL_UNKNOWN",
    "score_liquidation": "S6_MARKET_LIQUIDATION",
    "score_regulatory": "S5_REGULATORY_ENFORCEMENT",
}

SIGNAL_TYPES = {
    "score_hack": "attack_or_exploit_signal",
    "score_fraud": "fraud_signal",
    "score_outage": "exchange_or_operations_signal",
    "score_stablecoin": "stablecoin_or_reserve_signal",
    "score_solvency": "solvency_signal",
    "score_team": "governance_signal",
    "score_infra": "infrastructure_signal",
    "score_whale": "whale_onchain_signal",
    "score_volatility": "market_volatility_signal",
    "score_macro": "macro_signal",
    "score_liquidation": "liquidation_signal",
    "score_regulatory": "regulatory_signal",
}

DIRECT_HIGH_RISK_TYPES = {
    "score_hack",
    "score_fraud",
    "score_outage",
    "score_stablecoin",
    "score_solvency",
    "score_team",
    "score_infra",
}

THRESHOLD_HIGH_RISK_TYPES = {
    "score_whale",
    "score_volatility",
    "score_macro",
    "score_liquidation",
    "score_regulatory",
}

HIGH_RISK_FLOOR_RULES = {
    "score_hack": {
        "floor": 65,
        "trigger_score": 0.0,
        "groups": {
            "exploit": ["漏洞利用", "利用漏洞", "被利用", "exploit", "exploited"],
            "security_event": ["安全事件", "攻击事件", "被黑", "黑客攻击", "遭受攻击", "合约异常"],
            "abnormal_mint": ["无限铸币", "无限铸造", "异常铸造", "未授权铸造", "非法铸造", "被铸造"],
            "pause_interaction": ["暂勿交互", "暂停交互", "暂勿与", "不要交互", "避免交互", "合约暂停"],
            "official_warning": ["官方提醒", "官方建议", "建议用户", "安全团队", "项目方回应", "在 X 平台回应"],
        },
        "reason": "链上漏洞/攻击强信号组合",
    },
    "score_fraud": {
        "floor": 65,
        "trigger_score": 0.0,
        "groups": {
            "rug": ["Rug Pull", "rug pull", "跑路", "撤池", "抽走流动性"],
            "team": ["团队失联", "团队控制", "项目方失联", "社媒停更", "官网关闭"],
            "funds": ["资金转移", "资金外流", "卷走", "被转出", "提款异常"],
            "warning": ["官方提醒", "用户预警", "社区预警", "安全团队"],
        },
        "reason": "诈骗/跑路强信号组合",
    },
    "score_outage": {
        "floor": 65,
        "trigger_score": 0.0,
        "groups": {
            "withdrawal": ["暂停提现", "停止提现", "无法提现", "提现关闭", "提款冻结"],
            "platform": ["交易所", "平台", "钱包系统", "账户冻结"],
            "users": ["大量用户", "多个用户", "用户反馈", "社群反馈", "投诉"],
            "uncertain": ["恢复时间不明", "未说明恢复时间", "异常", "故障", "宕机"],
        },
        "reason": "交易所/系统运维强信号组合",
    },
    "score_stablecoin": {
        "floor": 65,
        "trigger_score": 0.0,
        "groups": {
            "depeg": ["脱锚", "失去锚定", "跌破 1 美元", "低于1美元", "偏离锚定"],
            "redemption": ["赎回压力", "挤兑", "无法赎回", "暂停赎回"],
            "liquidity": ["流动性枯竭", "流动性不足", "兑换量异常", "价差扩大"],
            "reserve": ["储备不足", "储备透明度", "审计缺失", "抵押不足"],
        },
        "reason": "稳定币/储备强信号组合",
    },
    "score_solvency": {
        "floor": 65,
        "trigger_score": 0.0,
        "groups": {
            "solvency": ["资不抵债", "偿付能力", "破产", "流动性危机", "坏账"],
            "reserve": ["储备不足", "准备金不足", "资产缺口", "负债缺口"],
            "withdrawal": ["暂停提现", "无法兑付", "挤兑", "赎回延迟"],
            "official": ["官方承认", "审计显示", "披露", "监管调查"],
        },
        "reason": "偿付/储备强信号组合",
    },
    "score_team": {
        "floor": 65,
        "trigger_score": 0.0,
        "groups": {
            "team": ["团队失联", "创始人失联", "高管离职", "核心团队离职"],
            "governance": ["治理异常", "权限变更", "多签变更", "控制权转移"],
            "funds": ["资金转移", "代币转出", "项目资金外流", "财库转移"],
            "warning": ["官方提醒", "社区预警", "安全团队", "用户预警"],
        },
        "reason": "项目治理/团队异常强信号组合",
    },
    "score_infra": {
        "floor": 65,
        "trigger_score": 0.0,
        "groups": {
            "halt": ["网络暂停", "出块停止", "链停止", "停止出块", "宕机"],
            "protocol": ["协议异常", "共识异常", "预言机异常", "跨链桥异常", "RPC 故障"],
            "impact": ["交易失败", "无法转账", "大面积影响", "用户受影响"],
            "official": ["官方确认", "官方提醒", "安全团队", "紧急修复"],
        },
        "reason": "基础设施/协议层强信号组合",
    },
    "score_liquidation": {
        "floor": 61,
        "trigger_score": 0.40,
        "groups": {
            "liquidation": ["爆仓", "清算", "连环清算", "强平"],
            "scale": ["大规模", "巨额", "大量", "全市场", "连锁"],
            "liquidity": ["流动性枯竭", "滑点扩大", "穿仓", "保险基金"],
            "market": ["市场冲击", "价格暴跌", "瀑布", "闪崩"],
        },
        "reason": "爆仓/清算强信号组合",
    },
    "score_whale": {
        "floor": 61,
        "trigger_score": 0.40,
        "groups": {
            "whale": ["巨鲸", "大户", "鲸鱼地址", "大额转账"],
            "exchange": ["转入交易所", "流入交易所", "交易所充值", "向交易所转入"],
            "scale": ["大额", "巨额", "多笔", "连续", "集中"],
            "market": ["抛售压力", "出货", "价格承压", "流动性冲击"],
        },
        "reason": "巨鲸/链上流向强信号组合",
    },
    "score_volatility": {
        "floor": 61,
        "trigger_score": 0.40,
        "groups": {
            "move": ["闪崩", "插针", "瀑布", "暴跌", "崩盘", "瞬间暴跌"],
            "scale": ["大幅", "剧烈", "异常", "短时", "日内"],
            "liquidity": ["流动性枯竭", "滑点", "买盘消失", "恐慌抛售"],
            "market": ["全市场", "主流币", "加密市场", "连锁反应"],
        },
        "reason": "异常行情波动强信号组合",
    },
    "score_macro": {
        "floor": 61,
        "trigger_score": 0.40,
        "groups": {
            "shock": ["战争", "军事行动", "制裁", "危机", "金融风暴", "地缘冲突"],
            "market": ["加密市场", "比特币", "以太坊", "币市", "数字资产市场"],
            "impact": ["暴跌", "流动性冲击", "避险情绪", "风险偏好下降", "市场冲击"],
            "policy": ["资本管制", "禁令", "封锁", "加息", "监管冲击"],
        },
        "reason": "宏观/政策冲击强信号组合",
    },
    "score_regulatory": {
        "floor": 61,
        "trigger_score": 0.40,
        "groups": {
            "enforcement": ["起诉", "指控", "罚款", "制裁", "查封", "逮捕"],
            "authority": ["SEC", "CFTC", "司法部", "监管机构", "法院", "检方"],
            "crypto": ["交易所", "稳定币", "代币", "加密", "DeFi"],
            "impact": ["禁止", "冻结", "停止服务", "下架", "业务暂停"],
        },
        "reason": "监管执法强信号组合",
    },
}

RISK_TYPE_ORDER = [
    "score_hack",
    "score_fraud",
    "score_outage",
    "score_stablecoin",
    "score_solvency",
    "score_team",
    "score_infra",
    "score_whale",
    "score_volatility",
    "score_macro",
    "score_liquidation",
    "score_regulatory",
]

NEGATIVE_PATTERNS = {
    "planned_maintenance": ["例行维护", "计划内维护", "系统升级", "常规维护"],
    "resolved_or_repaired": ["已恢复", "恢复正常", "已修复", "完成修复", "已解决"],
    "no_loss_or_no_impact": ["无资金损失", "未造成损失", "用户资金未受影响", "未受影响"],
    "discussion_only": ["讨论", "草案", "征求意见", "咨询", "监管框架", "呼吁", "建议", "观点", "分析称"],
    "security_research_only": ["安全研究", "漏洞披露", "审计报告", "漏洞赏金", "白帽"],
    "internal_transfer": ["内部调拨", "钱包归集", "冷钱包迁移", "官方钱包迁移"],
    "rumor_without_confirmation": ["传闻", "网传", "未经证实", "尚未发布公告", "没有链上", "缺少官方"],
    "normal_market_commentary": ["行情日报", "每日行情", "技术分析", "支撑位", "阻力位"],
    "positive_regulatory_clarity": ["法院驳回", "驳回", "放行", "批准", "豁免", "合规指引"],
    "ordinary_team_change": ["普通人事调整", "正常离职", "组织调整"],
}

CAP_RULES = [
    ("security_research_only", 45, "soft_cap", "安全研究或漏洞披露缺少已发生攻击证据"),
    ("planned_maintenance", 45, "soft_cap", "计划维护语境限制交易所异常高分"),
    ("resolved_or_repaired", 40, "soft_cap", "事件已恢复或修复"),
    ("discussion_only", 35, "soft_cap", "讨论、草案或观点类文本缺少实际风险事件"),
    ("internal_transfer", 30, "soft_cap", "内部归集或钱包迁移不能直接视作外部风险"),
    ("rumor_without_confirmation", 55, "soft_cap", "仅传闻或缺少官方/链上确认"),
    ("normal_market_commentary", 25, "soft_cap", "普通行情评论不能直接判为高风险事件"),
    ("positive_regulatory_clarity", 20, "soft_cap", "监管利好或指控被驳回"),
    ("ordinary_team_change", 35, "soft_cap", "普通团队变动不能直接判为高风险治理事件"),
]

NEGATIVE_SCENARIO_HINTS: dict[str, ScenarioId] = {
    "security_research_only": "S1_ATTACK_EXPLOIT",
    "planned_maintenance": "S2_EXCHANGE_ABNORMALITY",
    "rumor_without_confirmation": "S2_EXCHANGE_ABNORMALITY",
    "discussion_only": "S5_REGULATORY_ENFORCEMENT",
    "positive_regulatory_clarity": "S5_REGULATORY_ENFORCEMENT",
    "normal_market_commentary": "S6_MARKET_LIQUIDATION",
    "ordinary_team_change": "S7_FRAUD_GOVERNANCE",
}

# 命中阈值：用于 rule_types
TYPE_THRESHOLD = 0.30
# 主类别最低阈值降至0.08以召回更多真实风险
PRIMARY_TYPE_MIN = 0.08


def score_to_label(score_01: float) -> str:
    if score_01 >= 0.70:
        return "high"
    if score_01 >= 0.40:
        return "medium"
    return "low"


def score_all_risks(text: str) -> dict:
    if has_any(text, NEG_TICKER_COLLISION):
        zero_scores = {k: 0.0 for k in RISK_SCORERS.keys()}
        zero_scores["risk"] = 0
        zero_scores["rule_label"] = "low"
        zero_scores["rule_types"] = ""
        zero_scores["rule_primary_type"] = "无明显风险"
        return zero_scores

    raw_scores = {name: fn(text) for name, fn in RISK_SCORERS.items()}
    max_score_name = max(raw_scores, key=raw_scores.get)
    max_score_01 = raw_scores[max_score_name]

    # 主类别选取，对 score_macro 特殊处理：若它是最高分但低于0.3，尝试次选
    primary_type = "无明显风险"
    if max_score_01 >= PRIMARY_TYPE_MIN:
        if max_score_name == "score_macro" and max_score_01 < 0.3:
            # 寻找其他类别中分数最高且>=0.08的
            other_scores = {k: v for k, v in raw_scores.items() if k != "score_macro" and v >= PRIMARY_TYPE_MIN}
            if other_scores:
                second_name = max(other_scores, key=other_scores.get)
                primary_type = RISK_NAME_MAP[second_name]
            else:
                primary_type = "无明显风险"
        else:
            primary_type = RISK_NAME_MAP[max_score_name]

    effective_risk = int(round(max_score_01 * 100))
    effective_label = score_to_label(max_score_01) if max_score_01 > 0 else "low"

    hit_types = []
    for score_name, score_val in raw_scores.items():
        if score_val >= TYPE_THRESHOLD:
            hit_types.append(RISK_NAME_MAP[score_name])

    result = {name: round(val, 4) for name, val in raw_scores.items()}
    result["risk"] = effective_risk
    result["rule_label"] = effective_label
    result["rule_types"] = "|".join(hit_types)
    result["rule_primary_type"] = primary_type

    return result


def _matched_terms(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term in text or term.lower() in lowered]


def _negative_signals(text: str) -> list[Signal]:
    signals: list[Signal] = []
    for signal_type, terms in NEGATIVE_PATTERNS.items():
        hits = _matched_terms(text, terms)
        if hits:
            scenario = NEGATIVE_SCENARIO_HINTS.get(signal_type)
            signals.append(
                Signal(
                    type=signal_type,
                    matched_terms=hits,
                    strength=-0.25,
                    scenario_hint=scenario,
                    reason=f"命中缓和/排除语义：{signal_type}",
                )
            )
    return signals


def _cap_signals(negative_signals: list[Signal]) -> list[Signal]:
    negative_types = {signal.type for signal in negative_signals}
    caps: list[Signal] = []
    for signal_type, score_cap, cap_type, reason in CAP_RULES:
        if signal_type in negative_types:
            caps.append(
                Signal(
                    type=signal_type,
                    strength=-0.4,
                    score_cap=score_cap,
                    cap_type=cap_type,
                    reason=reason,
                )
            )
    return caps


def _risk_type_stats(raw_scores: dict[str, float]) -> list[dict[str, object]]:
    stats: list[dict[str, object]] = []
    for risk_type in RISK_TYPE_ORDER:
        score = float(raw_scores.get(risk_type, 0.0))
        if risk_type in DIRECT_HIGH_RISK_TYPES:
            route_group = "direct_high_risk"
            high_risk_path = score > 0
        else:
            route_group = "threshold_high_risk"
            high_risk_path = score > 0.40
        stats.append(
            {
                "risk_type": risk_type,
                "risk_name": RISK_NAME_MAP[risk_type],
                "scenario": RISK_SCENARIO_MAP[risk_type],
                "score": round(score, 4),
                "score_100": int(round(score * 100)),
                "hit": score > 0,
                "route_group": route_group,
                "high_risk_path": high_risk_path,
            }
        )
    return stats


def _high_risk_route(raw_scores: dict[str, float]) -> dict[str, object]:
    direct_hits = [
        risk_type
        for risk_type in RISK_TYPE_ORDER
        if risk_type in DIRECT_HIGH_RISK_TYPES and raw_scores.get(risk_type, 0.0) > 0
    ]
    threshold_hits = [
        risk_type
        for risk_type in RISK_TYPE_ORDER
        if risk_type in THRESHOLD_HIGH_RISK_TYPES and raw_scores.get(risk_type, 0.0) > 0.40
    ]
    triggered_types = direct_hits + threshold_hits
    return {
        "triggered": bool(triggered_types),
        "direct_hits": direct_hits,
        "threshold_hits": threshold_hits,
        "triggered_types": triggered_types,
        "rule": "direct_group_score_gt_0_or_threshold_group_score_gt_40",
    }


def _high_risk_floor_signals(text: str, raw_scores: dict[str, float]) -> list[dict[str, object]]:
    signals: list[dict[str, object]] = []
    for risk_type, rule in HIGH_RISK_FLOOR_RULES.items():
        score = float(raw_scores.get(risk_type, 0.0))
        trigger_score = float(rule["trigger_score"])
        if score <= trigger_score:
            continue
        groups = rule["groups"]
        matched_groups: list[str] = []
        matched_terms: dict[str, list[str]] = {}
        for group_name, terms in groups.items():
            hits = _matched_terms(text, terms)
            if hits:
                matched_groups.append(group_name)
                matched_terms[group_name] = hits
        if len(matched_groups) < 2:
            continue
        signals.append(
            {
                "risk_type": risk_type,
                "risk_name": RISK_NAME_MAP[risk_type],
                "scenario": RISK_SCENARIO_MAP[risk_type],
                "floor": int(rule["floor"]),
                "score_100": int(round(score * 100)),
                "matched_groups": matched_groups,
                "matched_terms": matched_terms,
                "reason": rule["reason"],
            }
        )
    return signals


def scan_fast_signals(text: str) -> SignalScanResult:
    cleaned = str(text or "")
    try:
        raw = score_all_risks(cleaned)
    except Exception as exc:
        return SignalScanResult(
            fast_exit_allowed=False,
            debug={"risk_scanner_error": str(exc)},
        )

    raw_scores = {
        risk_type: float(raw.get(risk_type, 0.0))
        for risk_type in RISK_TYPE_ORDER
    }
    risk_type_stats = _risk_type_stats(raw_scores)
    high_risk_route = _high_risk_route(raw_scores)
    high_risk_floor_signals = _high_risk_floor_signals(cleaned, raw_scores)

    scenario_scores: dict[ScenarioId, float] = {}
    positive: list[Signal] = []
    for risk_type in RISK_TYPE_ORDER:
        score = raw_scores.get(risk_type, 0.0)
        if score <= 0:
            continue
        scenario = RISK_SCENARIO_MAP[risk_type]
        scenario_scores[scenario] = max(scenario_scores.get(scenario, 0.0), score)
        positive.append(
            Signal(
                type=SIGNAL_TYPES.get(risk_type, risk_type),
                strength=score,
                scenario_hint=scenario,
                reason=RISK_NAME_MAP[risk_type],
            )
        )

    negative = _negative_signals(cleaned)
    caps = _cap_signals(negative)
    for signal in negative:
        if signal.scenario_hint:
            scenario_scores[signal.scenario_hint] = max(scenario_scores.get(signal.scenario_hint, 0.0), 0.1)

    hit_count = sum(1 for score in raw_scores.values() if score > 0)
    medium_count = sum(1 for score in raw_scores.values() if score >= TYPE_THRESHOLD)
    high_count = sum(1 for score in raw_scores.values() if score > 0.50)
    suggested_top_k = 1
    if hit_count >= 2 or medium_count >= 1:
        suggested_top_k = 2
    if medium_count >= 3:
        suggested_top_k = 3
    if high_count >= 3:
        suggested_top_k = 4

    return SignalScanResult(
        positive_signals=positive,
        negative_signals=negative,
        cap_signals=caps,
        scenario_scores=scenario_scores,
        raw_rule_scores=raw_scores,
        suggested_top_k=suggested_top_k,
        fast_exit_allowed=not bool(high_risk_route["triggered"]),
        debug={
            "risk": raw.get("risk"),
            "rule_label": raw.get("rule_label"),
            "rule_primary_type": raw.get("rule_primary_type"),
            "rule_types": raw.get("rule_types"),
            "risk_type_stats": risk_type_stats,
            "high_risk_route": high_risk_route,
            "high_risk_floor_signals": high_risk_floor_signals,
        },
    )


scan_risks = scan_fast_signals


def score_dataframe(df):
    if pd is None:
        raise RuntimeError("pandas is required for batch CSV scoring")

    # 优先拼接标题+内容；如果没有标题列，就只用内容
    df = df.copy()
    if "标题" in df.columns:
        df["标题"] = df["标题"].fillna("").astype(str)
    else:
        df["标题"] = ""

    df["内容"] = df["内容"].fillna("").astype(str)
    df["text"] = (df["标题"] + " " + df["内容"]).str.strip()
    score_df = df["text"].apply(lambda x: pd.Series(score_all_risks(x)))
    df_out = pd.concat([df, score_df], axis=1)

    base_cols = [c for c in ["新闻id", "时间", "标题", "内容", "链接"] if c in df_out.columns]
    score_cols = list(RISK_SCORERS.keys()) + ["risk", "rule_label", "rule_types", "rule_primary_type"]
    return df_out[base_cols + score_cols]


def run_batch(csv_path: str = CSV_PATH, out_path: str = OUT_PATH):
    if pd is None:
        raise RuntimeError("pandas is required for batch CSV scoring")

    df = pd.read_csv(csv_path)
    out_df = score_dataframe(df)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    return out_df


if __name__ == "__main__":
    out_df = run_batch()
    print("Saved:", OUT_PATH)
    print("\n总分分布：")
    print(out_df["risk"].describe())

    print("\n风险等级分布：")
    print(out_df["rule_label"].value_counts(dropna=False))

    print("\n主风险类别分布：")
    print(out_df["rule_primary_type"].value_counts(dropna=False).head(20))
