from __future__ import annotations

import unittest

from app.agents.chat_agent.prompts.low_risk_gate import build_low_risk_gate_prompt
from app.agents.chat_agent.schemas import RiskCaseInput
from app.agents.chat_agent.tools.risk_scanner import RISK_NAME_MAP, scan_fast_signals, score_all_risks


class SoftNewsRiskRecallTest(unittest.TestCase):
    def test_etf_outflow_is_recalled_as_volatility_risk(self) -> None:
        text = "比特币现货ETF上周净流出17.20亿美元，创历史第二高，机构情绪恶化。"

        result = score_all_risks(text)
        scan = scan_fast_signals(text)

        self.assertEqual(result["rule_primary_type"], "异常行情波动风险")
        self.assertGreaterEqual(result["risk"], 55)
        self.assertIn("score_volatility", scan.debug["high_risk_route"]["triggered_types"])

    def test_etf_net_inflow_with_minor_outflow_stays_low_risk(self) -> None:
        text = "SOL现货ETF上周净流入1563万美元，其中部分产品净流出56.31万美元。"

        result = score_all_risks(text)

        self.assertEqual(result["rule_primary_type"], "无明显风险")
        self.assertLessEqual(result["risk"], 25)

    def test_dex_tvl_collapse_is_recalled_as_volatility_risk(self) -> None:
        text = "Solana去中心化交易所DEX交易量两周内暴跌约82%，TVL周降约15%。"

        result = score_all_risks(text)

        self.assertEqual(result["rule_primary_type"], "异常行情波动风险")
        self.assertGreaterEqual(result["risk"], 65)

    def test_token_unlock_is_recalled_as_token_issuance_risk(self) -> None:
        text = "三大项目将解锁超6.55亿美元代币，HUMA解锁占供应20.04%。"

        result = score_all_risks(text)
        scan = scan_fast_signals(text)

        self.assertEqual(result["rule_primary_type"], "代币发行 / 异常增发风险")
        self.assertGreaterEqual(result["risk"], 50)
        self.assertIn("score_token_issuance", scan.debug["high_risk_route"]["direct_hits"])

    def test_auto_liquidation_exchange_action_is_recalled(self) -> None:
        text = "币安杠杆将移除多项杠杆交易对，并对相关仓位进行自动平仓和清算。"

        result = score_all_risks(text)
        scan = scan_fast_signals(text)

        self.assertEqual(result["rule_primary_type"], "爆仓 / 清算风险")
        self.assertGreaterEqual(result["risk"], 55)
        self.assertIn("score_outage", scan.debug["high_risk_route"]["direct_hits"])
        self.assertIn("score_liquidation", scan.debug["high_risk_route"]["threshold_hits"])

    def test_basis_trade_drawdown_is_liquidation_risk(self) -> None:
        text = (
            "PiggyBank披露LAB事件：协议发生约57.9万美元净回撤，"
            "一笔LAB代币基差交易遭遇市场操纵，资金费率年化-17000%，空头被迫平仓。"
        )

        result = score_all_risks(text)

        self.assertEqual(result["rule_primary_type"], "爆仓 / 清算风险")
        self.assertGreaterEqual(result["risk"], 65)

    def test_realized_whale_short_loss_is_liquidation_not_hack(self) -> None:
        text = "加密鲸鱼关闭HYPE空头，锁定4,646万美元损失并支付资金费用，随后开设2倍杠杆多头。"

        result = score_all_risks(text)

        self.assertEqual(result["rule_primary_type"], "爆仓 / 清算风险")
        self.assertGreaterEqual(result["risk"], 70)
        self.assertEqual(result.get("score_hack", 0), 0.0)

    def test_options_expiry_pressure_is_volatility_risk(self) -> None:
        text = "比特币困于7.5万至8万美元区间，66亿美元期权到期在即，价格被关键链上支撑和短期持有者成本压制。"

        result = score_all_risks(text)

        self.assertEqual(result["rule_primary_type"], "异常行情波动风险")
        self.assertGreaterEqual(result["risk"], 50)

    def test_risk_off_macro_report_is_macro_risk(self) -> None:
        text = "分析师称比特币进入Risk-off风险规避阶段，宏观环境急剧恶化，美债收益率上行，ETF需求动能远低于峰值。"

        result = score_all_risks(text)
        scan = scan_fast_signals(text)

        self.assertEqual(result["rule_primary_type"], "宏观 / 政策冲击风险")
        self.assertGreaterEqual(result["risk"], 60)
        self.assertTrue(any(item["risk_type"] == "score_macro" for item in scan.debug["high_risk_floor_signals"]))

    def test_net_loss_financial_report_is_solvency_risk_not_macro(self) -> None:
        text = "Cango公布Q1财报，受比特币市场价格下跌影响净亏损2.611亿美元，长期债务下降但仍持有大量比特币储备。"

        result = score_all_risks(text)

        self.assertEqual(result["rule_primary_type"], "偿付能力 / 储备 / 流动性风险")
        self.assertGreaterEqual(result["risk"], 55)

    def test_nft_market_cap_decline_is_volatility_not_solvency(self) -> None:
        text = "以太坊下跌拖累NFT市场总市值回落至历史低位，蓝筹NFT地板价承压，部分系列几乎无成交。"

        result = score_all_risks(text)

        self.assertEqual(result["rule_primary_type"], "异常行情波动风险")
        self.assertGreaterEqual(result["risk"], 50)

    def test_corporate_treasury_eth_concentration_is_whale_risk(self) -> None:
        text = "BitMine上周购入11.19万枚ETH，创最大单周购买纪录，总持仓近540万枚ETH，约占以太坊流通供应量4.47%。"

        result = score_all_risks(text)
        scan = scan_fast_signals(text)

        self.assertEqual(result["rule_primary_type"], "大额转账 / 巨鲸行为风险")
        self.assertGreaterEqual(result["risk"], 55)
        self.assertTrue(any(item["risk_type"] == "score_whale" for item in scan.debug["high_risk_floor_signals"]))

    def test_plain_spot_listing_stays_low_risk(self) -> None:
        text = "币安将上线Genius Terminal现货交易对，开放充值提现。"

        result = score_all_risks(text)

        self.assertEqual(result["rule_primary_type"], "无明显风险")
        self.assertLessEqual(result["risk"], 25)

    def test_plain_contract_listing_after_gain_stays_low_risk(self) -> None:
        text = "QNT合约上线以来累计上涨30.5%，某链上交易员5倍杠杆做多录得浮盈。"

        result = score_all_risks(text)

        self.assertEqual(result["rule_primary_type"], "无明显风险")
        self.assertLessEqual(result["risk"], 25)

    def test_positive_bridge_inflow_stays_low_risk(self) -> None:
        text = "Hyperliquid跨链桥USDC净流入突破1.73亿美元并创近10个月新高，平台未平仓合约量上升。"

        result = score_all_risks(text)
        scan = scan_fast_signals(text)

        self.assertEqual(result["rule_primary_type"], "无明显风险")
        self.assertLessEqual(result["risk"], 25)
        self.assertNotIn("score_bridge", scan.debug["high_risk_route"]["direct_hits"])

    def test_long_term_price_prediction_stays_general_low_risk(self) -> None:
        text = "Tom Lee表示预计以太坊最终可能达到25万美元，Bitmine持有大量ETH并看好长期质押模型。"

        result = score_all_risks(text)

        self.assertEqual(result["rule_primary_type"], "无明显风险")
        self.assertLessEqual(result["risk"], 20)

    def test_asset_tokenization_progress_stays_low_risk(self) -> None:
        text = "华尔街与欧洲机构加速推进资产代币化，纳斯达克试点获批，纽交所联手Securitize。"

        result = score_all_risks(text)
        scan = scan_fast_signals(text)

        self.assertLessEqual(result["risk"], 25)
        self.assertNotIn("score_regulatory", scan.debug["high_risk_route"]["threshold_hits"])

    def test_mica_consultation_is_low_regulatory_risk(self) -> None:
        text = "欧盟启动MiCA法规审查并公开咨询，评估稳定币储备要求、DeFi、质押和市场诚信规则是否需要更新。"

        result = score_all_risks(text)

        self.assertEqual(result["rule_primary_type"], "监管与法律风险")
        self.assertLessEqual(result["risk"], 35)

    def test_cross_chain_bridge_shutdown_prefers_bridge_risk(self) -> None:
        text = "Toncoin官方宣布跨链桥将永久关闭，9月1日后停止所有转账功能，用户需在截止日期前提取未回收资产。"

        result = score_all_risks(text)

        self.assertEqual(result["rule_primary_type"], "跨链桥 / 跨链资金风险")
        self.assertGreaterEqual(result["risk"], 55)

    def test_positive_stablecoin_reserve_disclosure_stays_low_risk(self) -> None:
        text = "Circle 发行 USDC 流通量增加 4 亿枚，USDC 储备量约为 771 亿美元，主要为国债和现金。"

        result = score_all_risks(text)

        self.assertEqual(result["rule_primary_type"], "无明显风险")
        self.assertLessEqual(result["risk"], 25)

    def test_perp_funding_rate_is_not_stablecoin_depeg(self) -> None:
        text = "币安合约将把SPCXUSDT Pre-IPO永续合约转换为标准版，资金费率最高和最低可达+1.00%/-1.00%。"

        result = score_all_risks(text)

        self.assertNotEqual(result["rule_primary_type"], "稳定币异常风险")
        self.assertLessEqual(result.get("score_stablecoin", 0), 0.0)

    def test_new_token_drawdown_and_unlock_pressure_is_recalled(self) -> None:
        text = "Delphi称新币中位数跌幅达82%，代币按固定时间解锁，空投演变为退出流动性，回购未必覆盖解锁抛压。"

        result = score_all_risks(text)

        self.assertEqual(result["rule_primary_type"], "代币发行 / 异常增发风险")
        self.assertGreaterEqual(result["risk"], 70)

    def test_bridge_attack_recovery_still_keeps_bridge_risk(self) -> None:
        text = "Aave遭跨链攻击，LayerZero跨链桥接受伪造消息释放rsETH，攻击者借出WETH，资产随后已恢复。"

        result = score_all_risks(text)

        self.assertEqual(result["rule_primary_type"], "跨链桥 / 跨链资金风险")
        self.assertGreaterEqual(result["risk"], 80)

    def test_attacker_tornado_flow_is_recalled_as_hack_risk(self) -> None:
        text = "MapProtocol 攻击者将 1B 代币兑换为 52.21 ETH 并存入 Tornadocash，代币已下跌 97%。"

        result = score_all_risks(text)

        self.assertEqual(result["rule_primary_type"], "链上漏洞 / 攻击风险")
        self.assertGreaterEqual(result["risk"], 80)

    def test_low_risk_gate_prompt_lists_all_risk_types(self) -> None:
        text = "比特币现货ETF上周净流出17.20亿美元，创历史第二高。"
        case_input = RiskCaseInput(case_id="prompt-test", raw_text=text, content=text)
        scan = scan_fast_signals(text)

        prompt = build_low_risk_gate_prompt(case_input, scan)

        self.assertIn(f"全部 {len(RISK_NAME_MAP)} 类 risk_type", prompt)
        for risk_type, risk_name in RISK_NAME_MAP.items():
            self.assertIn(risk_type, prompt)
            self.assertIn(risk_name, prompt)


if __name__ == "__main__":
    unittest.main()
