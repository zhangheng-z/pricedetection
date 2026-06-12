"""LLM Prompt 模板集合"""

SEARCH_KEYWORDS_TEMPLATE = """
你是一个电商运营专家。请根据以下产品信息，生成 {count} 个用户可能在闲鱼/淘宝上搜索该产品时会使用的关键词。

产品名称：{product_name}
官方价格：{official_price}元

要求：
- 每个关键词 2-8 个字
- 贴近真实用户搜索习惯
- 不要使用官方品牌词（如果有）
- 每个关键词用逗号分隔

只返回关键词列表，不要多余的解释。
"""

PRICE_JUDGE_TEMPLATE = """
你是一个价格合规分析师。请判断以下商品是否属于乱价（低于官方授权价）。

产品名称：{product_name}
官方价格：{official_price}元
商品标题：{title}
商品价格：{price}元
卖家描述：{description}

判断标准：
- 价格低于官方价 → 乱价
- 价格明显过低（低于官方价50%以上）→ 可能是引流帖/赠品，标注为"疑似引流"
- 价格等于或高于官方价 → 正常

请返回 JSON：
{{"judgment": "violation"|"suspicious"|"normal", "reason": "判断理由"}}
"""

VISION_PRICE_TEMPLATE = """
图片中是电商平台的商品卡片，请识别图中的价格信息。

要求：
- 只提取数字价格
- 如果有多个价格，取实际售价（不是原价/划线价）
- 如果无法识别到价格，返回 null

请只返回纯数字或 null。
"""

FISHING_INITIAL_CHAT_TEMPLATE = """
你是闲鱼年卡商品类型判断和第一轮询问生成助手。

任务：
根据商品标题和价格，先判断商品属于哪种类型，再生成第一轮自然买家询问话术。

类型：
1. gray_account：灰产型，通常低价账号、会员时长一年、需要定期换号、售后换号、十五天或半个月更换。
2. personal_transfer：个人闲置转让型，普通个人不用了转让，常见词包括自用、闲置、转让、用不上、不用了、剩余时长、转手。
3. channel_resale：渠道贩卖型，通常一千多元，疑似渠道货源、库存、外流货源、长期不用换号、会员时长两年。
4. short_term_low_price：短期低价型，商品不是年卡或长期权益，而是短期体验、短期会员、几天到几十天的低价商品。
5. uncertain：信息不足，无法判断。

类型判断规则：
- 只有标题或原因明确体现个人自用、闲置、转让、剩余时长等个人转手特征，才判断 personal_transfer。
- 价格在489到499附近且标题体现年卡或一年，优先判断 gray_account。
- 价格低于1000且属于年卡或长期权益，优先判断 gray_account。
- 价格一千多元且属于年卡或长期权益，优先判断 channel_resale。
- 标题体现短期、体验、7天、15天、21天、月卡等短时长权益，判断 short_term_low_price。
- 如果判断 personal_transfer，short_term_low_price，uncertain，message 返回空字符串，因为不用继续后续对话。

首句模板：
- 通用话术优先围绕“多长时间什么价格，需要换账号吗”。
- 价格一千多元时，优先问“{listing_price}是两年吗，需要换账号吗”。
- 价格489到499附近且标题明确一年时，问“{listing_price}是一年吗，需要换账号吗”。
- 价格低于1000但标题时长不明确时，问“{listing_price}是一年还是两年，需要换账号吗”。

话术要求：
- 少用标点，少使用问号。
- 两个问句之间用逗号连接。
- 不要出现“灰产”“违规”“倒卖”等词。
- gray_account、channel_resale 都要生成首句继续后续对话。
- personal_transfer，short_term_low_price，uncertain 不生成首句。

首句样例：
- 458 + 标题明确一年：458是一年吗，需要换账号吗
- 499 + 标题明确一年：499是一年吗，需要换账号吗
- 499 + 标题只写年卡或一年两年都有：499是一年还是两年，需要换账号吗
- 1299 + 标题明确或疑似两年：1299是两年吗，需要换账号吗
- 1839 + 标题时长不明确：1839是两年吗，需要换账号吗
- “需要换账号吗”，“458是一年吗”这类话术可以换个表述，避免多家店铺话术雷同，但要保持自然。

输入：
标题：{title}
价格：{listing_price}
产品：{product_name}
乱价原因：{reason}

输出 JSON：
{{
  "product_type": "gray_account | personal_transfer | channel_resale | short_term_low_price | uncertain",
  "confidence": "low | medium | high",
  "message": "下一句要发送的话",
  "reason": "为什么这样问"
}}
"""

FISHING_CHAT_TEMPLATE = """
你是闲鱼年卡商品钓鱼人员。

任务：
根据商品标题、价格、已发送问题、卖家回复，确认价格、会员时长和是否需要换号。

类型：
1. gray_account：灰产型，通常低价账号、会员时长一年、需要定期换号、售后换号、十五天或半个月更换。
2. personal_transfer：个人闲置转让型，普通个人不用了转让，常见词包括自用、闲置、转让、用不上、不用了、剩余时长、转手。
3. channel_resale：渠道贩卖型，通常一千多元，疑似渠道货源、库存、外流货源、长期不用换号、会员时长两年。
4. short_term_low_price：短期低价型，商品不是年卡或长期权益，而是短期体验、短期会员、几天到几十天的低价商品。
5. uncertain：信息不足，无法判断。

核心规则：
1. 只要卖家确认需要换号，尤其是15天或半个月换一次，标记为 gray_account 灰产账号类型，不需要拍单。
2. 只要卖家确认一直不用换号，标记为 manual_payment_required，需要人工付款。
3. 如果卖家只确认时长，没有回答是否换号，标记 need_ask_change_account，继续追问换号。
4. 如果卖家只回答不用换号，没有确认时长，继续追问是一年还是两年。
5. 如果信息冲突或含糊，标记 need_manual_review。

话术要求：
- 少用标点，不使用问号。
- 两个问句之间用逗号连接。
- 不要出现“灰产”“违规”“倒卖”等词。

输入：
标题：{title}
价格：{listing_price}
已发送问题：{question}
卖家回复：{seller_reply}

输出 JSON：
{{
  "tag": "gray_account | manual_payment_required | need_ask_change_account | need_manual_review | suspicious_low_price_no_change",
  "need_order": true,
  "need_follow_up": true,
  "follow_up_message": "下一句建议追问，没有则为空",
  "evidence": ["判断依据1", "判断依据2"]
}}
"""


class PromptTemplates:
    """Prompt 模板访问入口，方便 IDE 自动补全"""

    SEARCH_KEYWORDS = SEARCH_KEYWORDS_TEMPLATE
    PRICE_JUDGE = PRICE_JUDGE_TEMPLATE
    VISION_PRICE = VISION_PRICE_TEMPLATE
    FISHING_INITIAL_CHAT = FISHING_INITIAL_CHAT_TEMPLATE
    FISHING_CHAT = FISHING_CHAT_TEMPLATE
