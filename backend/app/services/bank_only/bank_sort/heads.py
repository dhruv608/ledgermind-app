"""The heads a bank line can be sorted into, their firm codes, the firm's starting rules on the payee, and the
sorted line itself."""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from backend.app.services.bank_only.input_files import BankLine, Invoice

CUSTOMER = "Customer receipt"
SUPPLIER = "Supplier bill paid"
DIRECTOR = "Director's loan"
UNSORTED = "Unsorted"
TRANSFER = "Transfer between own accounts"
# A statement's own 'Opening balance adjustment' line: money already in the account, never a sale. In the company's
# first period it was there before the company was formed, so it is the director's money; otherwise last year's
# closing balance tells what it is
OPENING_MONEY = re.compile(r"^\s*opening balance", re.I)
TRANSFERS = 9998                # the accountant's in-between account for money moved between the client's accounts
# Rules whose head depends on the client's industry: a supermarket / food wholesaler is stock for a food
# business and personal otherwise; a builders' merchant is materials for construction and repairs otherwise
FOOD_SHOP, DIY_STORE = "<food shop>", "<builders merchant>"
# Clothes, gifts and leisure: the director's own spending, unless the client sells such things (a retailer's stock)
PERSONAL_SHOP = "<personal shop>"
FOOD_INDUSTRIES = {"RES"}
BY_INDUSTRY = {
    FOOD_SHOP: lambda industry: ("Purchases (no bill)", True) if industry in FOOD_INDUSTRIES
    else ("Personal (director's loan)", False),
    PERSONAL_SHOP: lambda industry: ("Purchases (no bill)", False) if industry == "RTL"
    else ("Personal (director's loan)", False),
    # Industry not set: materials / purchases
    DIY_STORE: lambda industry: ("Repairs and maintenance", True) if industry and industry != "CON"
    else ("Purchases (no bill)", True),
}

# Head -> firm code (None: decided by a later step, e.g. customer receipts go to debtors or sales after matching)
HEAD_CODES: Dict[str, Optional[int]] = {
    CUSTOMER: None, SUPPLIER: 5200, DIRECTOR: 5400, UNSORTED: 9999,
    "Purchases (no bill)": 1400, "Vehicle running costs": 3230, "Insurance": 3260, "Subscriptions": 3320,
    "Accountancy fees": 3301, "Computer software": 3240, "Telephone and internet": 3290, "Bank charges": 3351,
    "Corporation tax paid": 5310, "VAT paid": 5300, "PAYE and NI paid": 5320, "Net wages": 5330,
    "Bank interest received": 900, "Donations": 3360, "Refund received": None, TRANSFER: TRANSFERS,
    "HMRC (check which tax)": None,
    # From the firm's chart keyword rules, mostly for bank-only clients with no bills to match
    "Travel and subsistence": 3081, "Light and heat": 3130, "Water rates": 3131, "Rates": 3110, "Security": 3160,
    "Advertising": 3280, "Postage": 3273, "Courier": 2712, "Pension paid": 5352, "Legal fees": 3302,
    "Filing fees": 3309, "Card charges": 3352, "Loan repayment": 5100, "Vehicle finance (HP)": 5001,
    "Vehicle hire": 3215, "Repairs and maintenance": 3140, "Sales (card takings)": 0,
    "Personal (director's loan)": 5400, "Cash withdrawn": 5400,
    # Chosen by the accountant on the Books tab: money in with no invoice recorded straight to sales, or a line
    # left in suspense until the client answers
    "Sales (no invoice)": 0, "Ask the client": 9999,
}

# The firm's starting rules: (pattern on the bank description, head, which way the money goes: in / out / any)
RULES: List[Tuple[str, str, str]] = [
    (r"\bhmrc\b.*\b(cotax|corporation)\b|\bcotax\b|\bhmrc\b.*\bshipley\b", "Corporation tax paid", "out"),
    (r"\bhmrc\b.*\bvat\b", "VAT paid", "out"),
    (r"\bhmrc\b.*\b(paye|nic?|cumbernauld|ndds)\b", "PAYE and NI paid", "out"),
    (r"\bhmrc\b", "HMRC (check which tax)", "any"),
    # Card takings paid in by the card machine company: sales (its fees, money out, are card charges)
    (r"sumup|zettle|\bstripe\b|square ?up|takepayments|\bdojo\b|worldpay|paymentsense|^bcard\d|barclaycard|elavon|"
     r"merchant services|card ?net\b|global payments|evo payments|first data|card takings", "Sales (card takings)", "in"),
    (r"sumup|zettle|\bstripe\b|square ?up|takepayments|\bdojo\b|worldpay|paymentsense|elavon|merchant services|"
     r"card ?net\b|global payments|evo payments|first data|^ems\b", "Card charges", "out"),
    (r"alphera|motonovo|black horse|close ?bro(thers)?.*(mot|fin)|closebrosmotfin|santander consumer|"
     r"(vw|bmw|mercedes|toyota|ford) (financial|finance)", "Vehicle finance (HP)", "out"),
    (r"\bpfs\b|pay ?at ?pump|payatpump|petrol station", "Vehicle running costs", "out"),
    (r"enterprise rent|europcar|\bhertz\b|\bavis\b|\bsixt\b", "Vehicle hire", "out"),
    (r"\bdvla\b|clean air zone|\bcaz\b|\bfuel\b|petrol|\bgarage\b|\bshell\b|\besso\b|\btexaco\b|"
     r"\bparking\b|car ?park|paybyphone|\bncp\b|ringgo|congestion|dart charge|\btoll\b|\bmot\b|\btyres?\b|kwik fit|halfords|"
     r"service station|filling station|car wash|hand car",
     "Vehicle running costs", "out"),
    (r"justgiving|donation|\bcharity\b|gofundme|\baid\b|\brelief\b", "Donations", "out"),
    (r"motoring|breakdown|\brac\b|green flag|\bdvsa\b", "Vehicle running costs", "out"),
    (r"insurance|\badmiral\b|\baviva\b|\baxa\b|hiscox|simply business|direct line|\bqdos\b|\besure\b|\bassce\b|"
     r"assurance|legal ?& ?general|\blv=|zurich|royal london", "Insurance", "out"),
    (r"accountan|taxassist|bookkeep|family financial|ignition ?pay|practice ?ignition", "Accountancy fees", "out"),
    (r"solicitor|\blegal\b|law firm|\blaw\b", "Legal fees", "out"),
    (r"companies house|information commissioner|\bico\b", "Filing fees", "out"),
    (r"\bnest\b|people'?s pension|smart pension|now pensions", "Pension paid", "out"),
    (r"directors?'?s? loan|\bdla\b", DIRECTOR, "any"),
    (r"loan repayment|prtnr fin|funding circle|\biwoca\b|\bloan\b|mortgages?\b|landbay|paragon (bank|mortgage)|"
     r"precise mortgage|kent reliance|aldermore|shawbrook|together money|interbay|onesavings", "Loan repayment", "out"),
    # A credit card paid off from the bank: money moved to the card's account (its statement shows the spending)
    (r"barclaycard|american express|\bamex\b|capital one|capital on tap|credit card (payment|repayment)|"
     r"\bnw business credit\b",
     TRANSFER, "out"),
    # Personal unless the client shows otherwise (Apple bill, Netflix, Spotify, Amazon Prime)
    (r"netflix|spotify|apple\.com/bill|disney|amazon prime|prime video|now tv|playstation|xbox|uber ?eats|"
     r"deliveroo|just ?eat", "Personal (director's loan)", "out"),
    (r"\buber\b|\bbolt\b|trainline|\blner\b|avanti|northern ?rail|\btfl\b|transport for london|ryanair|easyjet|"
     r"\bjet2\b|british airways|airways|airlines?\b|\btaxi\b|addison lee|national express|megabus|booking\.com|"
     r"airbnb|expedia|travelodge|premier inn|\bhotels?\b|\bhilton\b|marriott|holiday inn|\bibis\b|\bveezu\b|"
     r"\bcabs?\b|free ?now|\bgett\b",
     "Travel and subsistence", "out"),
    (r"octopus|\bovo\b|british gas|\bedf\b|e\.on|eon next|scottish power|pozitive|shell energy|opus (gas|energy)|"
     r"\bnpower\b|utility warehouse|\bsse\b|\bgas supply\b|electricity", "Light and heat", "out"),
    (r"united utilities|severn trent|thames water|yorkshire water|anglian water|southern water|wessex water|"
     r"water plus|\bwater\b", "Water rates", "out"),
    (r"\bcounci|\.gov\.uk|business rates", "Rates", "out"),           # bank text cuts 'Council' to 'Counci'
    (r"verisure|\badt\b|\bcctv\b", "Security", "out"),
    # 'Facebk *4y353qyev2': the bank's short name for Facebook ads
    (r"facebook|facebk|\bmeta\b|\bfb\b|google ads|tiktok|mailchimp|linkedin|instagram", "Advertising", "out"),
    (r"royal mail|post office|\bpostage\b", "Postage", "out"),
    (r"\bdpd\b|\bevri\b|hermes|parcelforce|\bups\b|fedex|\bdhl\b|yodel", "Courier", "out"),
    (r"\batm\b|cash withdrawal|cash machine", "Cash withdrawn", "out"),
    (r"association|membership|subscription|\binstitute\b|docusign|experian|creditsafe|endole", "Subscriptions", "out"),
    (r"microsoft|google|adobe|\bxero\b|quickbooks|intuit|dropbox|apple\.com|icloud|zoom\.us|canva|open ?ai|chatgpt|"
     r"fasthosts|godaddy|shopify|figma|\bwix\b|squarespace|123-?reg|\bionos\b|hostinger|namecheap|\bslack\b|\bnotion\b|"
     r"instant ink|clearbusiness|wordpress|mailgun|hubspot|\bmonday\.com|\bzoom\b|zapier|typeform|airtable|"
     r"highlevel", "Computer software", "out"),
    # Online marketplaces for stock and small purchases
    (r"aliexpress|alibaba|\btemu\b", "Purchases (no bill)", "out"),
    # Shops whose spend is the business's stock only for a food business, else personal
    (r"\basda\b|\btesco\b|\baldi\b|\blidl\b|sainsbury|morrisons|\bco-?op\b|iceland|waitrose|home bargains|\bb ?& ?m\b|"
     r"poundland|wing yip|\bhalal\b|seafood|butcher|boucherie|cash (and|&) carry|superstore|supe?r ?t?market|"
     r"general stor|mini ?market|"
     r"bestway|\bbrakes\b|\blwc\b|spice foods|\bfoods?\b", FOOD_SHOP, "out"),
    # Clothes and fashion, jewellery, gifts, leisure and betting (a hotel spa is travel, caught above)
    (r"primark|shein|t ?\.? ?k ?\.? ?maxx|\bzara\b|\bh ?& ?m\b|river island|\basos\b|boohoo|pretty ?little ?thing|"
     r"new look|\bdune\b|j ?d sports|sports direct|decathlon|michael kors|watch station|pandora|h samuel|ernest jones|"
     r"selfridges|harrods|debenhams|matalan|uniqlo|\bmango\b|\bgap\b|foot ?locker|\bnike\b|adidas|\bclarks\b|"
     r"\bschuh\b|florist|champneys|cinema|odeon|cineworld|\bvue\b|ticketmaster|\bcasino\b|betfair|bet365|"
     r"paddy ?power|ladbrokes|william hill|\bsky ?bet\b|lottery|smyths|the entertainer|\bjewel|perfume|fragrance|"
     r"sephora|\blush\b", PERSONAL_SHOP, "out"),
    # Builders' merchants: materials for construction, else repairs
    (r"selco|toolstation|screwfix|wickes|\bb ?& ?q\b|travis perkins|jewson|howdens|wolseley", DIY_STORE, "out"),
    (r"communications|telecom|broadband|talkmobile|lebara|lycamobile|smarty|vodafone|\bo2\b|\bee limited\b|giffgaff|virgin media|\bbt group\b|\bbt\b|sky digital|talktalk|plusnet|"
     r"\bmobile\b|\bh3g\b|\bthree\b|^\s*(internet|telephone)\s*$",
     "Telephone and internet", "out"),
    (r"\bebay\b|\bamazon\b|\bamzn\b|plumb|merchants?\b|wholesale|builders|electrical|timber|\bcostco\b|\bbooker\b|"
     r"workwear|thermotechnology|heating", "Purchases (no bill)", "out"),
    # Meals out: subsistence (travel and subsistence 3081); a 'restaurant wholesale' supplier is caught
    # by the purchases rule above first
    (r"\bkfc\b|mcdonald|nando|greggs|starbucks|\bcosta\b|\bpret\b|subway|burger king|pizza|\bcafe\b|caffe|"
     r"coffee|restaurant|juice bar|boost juice|wetherspoon|\bpub\b", "Travel and subsistence", "out"),
    # An online bank's own plan fee ('Revolut Business Fee Grow plan fee', 'Monzo Business Pro', 'Tide Plus')
    (r"revolut business fee|monzo business (pro|team|plan)|\btide (plus|pro|cashback|plan)\b|starling .*\bfee\b|"
     r"\bplan fee\b|account fee|monthly fee|overdraft|non-?sterling|non[- ]?gbp|transaction fee|\bcharges?\b$|"
     r"^\s*(service )?charges?\b|finance charge|commission charge|foreign (transaction|exchange) fee",
     "Bank charges", "out"),
    (r"\binterest\b", "Bank interest received", "in"),
    (r"\brefund\b", "Refund received", "in"),
    (r"\bsavings?\b|own account|\bto isa\b|\bfrom isa\b|transfer (to|from) .*account|transfer (to|from) pot\b|"
     r"self[- ]?transfer|"
     r"transfer(ring)? funds|payment,? thank you|payment received - thank", TRANSFER, "any"),
    (r"\bpayrol|\bwages?\b|\bsall?[ae]ry\b|\bsall?ery\b|\bpayroll\b", "Net wages", "out"),
]
_RULES = [(re.compile(p, re.I), head, way) for p, head, way in RULES]
# Heads from the chart keyword rules, and the shops whose head follows the industry: a client's own Dext
# supplier named on the line comes first
GUIDE_HEADS = {"Travel and subsistence", "Light and heat", "Water rates", "Rates", "Security", "Advertising", "Postage",
               "Courier", "Pension paid", "Legal fees", "Filing fees", "Card charges", "Loan repayment",
               "Vehicle finance (HP)", "Vehicle hire", "Personal (director's loan)", "Cash withdrawn", FOOD_SHOP, PERSONAL_SHOP}
# Heads a rule only suggests: the accountant checks each line
UNSURE_HEADS = {"HMRC (check which tax)", "Refund received", TRANSFER, "Loan repayment", "Vehicle finance (HP)",
                "Personal (director's loan)", "Cash withdrawn", "Rates"}

@dataclass
class SortedLine:
    line: BankLine
    head: str
    code: Optional[int]
    how: str                                  # why: "invoice BD200607", "customer Example Ltd", "bill row 12", "rule: DVLA"
    sure: bool                                # False: the accountant should look at it
    bill: Optional[Invoice] = None            # the Dext bill this payment settles (supplier bills)
    customer: str = ""                        # the customer this receipt is from
    pair: Optional[BankLine] = None           # a transfer: the same money on the other account's statement


@dataclass
class BankSort:
    lines: List[SortedLine] = field(default_factory=list)

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for s in self.lines:
            out[s.head] = out.get(s.head, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))
