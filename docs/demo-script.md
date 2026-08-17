# OnRecord demo script

Runtime 4 minutes. Short version 90 seconds, marked at the bottom.
One tab: `https://onrecord-production-842c.up.railway.app`

All numbers verified against production on 2026-08-17. If the screen shows
something different, say what is on the screen.

---

## Pre-flight

Do not deploy today. Run this to confirm the numbers and warm every path:

```bash
B=https://onrecord-production-842c.up.railway.app
curl -s "$B/api/stats"                 # 309,662 docs, v3, 51 jurisdictions
curl -s "$B/api/promises" | head -c 60 # total 1527
curl -s "$B/api/outcomes/summary"      # followed_up 493, quiet 780
curl -s "$B/api/metrics" | head -c 60  # 7 rows
for m in lexical semantic hybrid; do
  curl -s -o /dev/null "$B/api/search?q=how+much+water+does+a+data+center+use&mode=$m&k=10"
done
curl -s -X POST "$B/api/answer" -H 'content-type: application/json' \
  -d '{"question":"What water commitments have data center operators made in county hearings?"}' -o /dev/null
```

Timings to expect: lexical 0.6s on one word and 7s on a long question, semantic
4.5s, hybrid 5.5s, a grounded answer 13s, a refusal 4s.

---

## 1. What this is (0:00)

**Do:** Search tab, loaded.

**Say:**
> OnRecord searches the paper trail behind the AI data center buildout.
> Three hundred nine thousand documents. County hearing transcripts, city
> council agendas, and SEC filings across fifty one jurisdictions.

---

## 2. Search and receipts (0:25)

**Do:** Type `how much water does a data center use`. Enter. Lexical is selected.

**Say:**
> Keyword search over an inverted index I built, with BM25 ranking.

**Do:** Click the receipt link on a county result. The hearing video opens at the timestamp.

**Say:**
> Every row carries a receipt. This one opens the hearing at the second those
> words were spoken.

**Do:** Return to the tab. Click Semantic. Then Hybrid.

**Say:**
> Same question, three retrieval modes. Semantic uses embeddings. Hybrid fuses
> both rankings. On a long question semantic returns faster than keyword search,
> because every extra word is another posting list to merge.

---

## 3. The Ledger (1:10)

**Do:** Ledger tab.

**Say:**
> This is what the record promised. Fifteen hundred commitments, pulled as exact
> quotes. Sixty six thousand megawatts, sixty eight thousand jobs, two hundred
> thirty three billion dollars.

**Do:** Point at the FOLLOWED UP tile.

**Say:**
> Four hundred ninety three of those promises turn up again in later meetings.
> Seven hundred eighty have gone quiet.

**Do:** Scroll to a promise card showing a follow-up chip.

**Say:**
> Each card gives the quote, the receipt, and where the record picked it back
> up. The system reports what it finds. It never rules on whether a promise was
> kept.

**Do:** Point at the grid tile.

**Say:**
> Eleven thousand eight hundred megawatts are filed with grid operators for
> these counties. Those two figures stay separate on purpose.

---

## 4. Ask (2:00)

**Do:** Ask tab. Type `What water commitments have data center operators made in county hearings?` Enter. Wait about 13 seconds.

**Say while it runs:**
> This retrieves first, then writes an answer that cites what it used.

**Do:** Answer appears with numbered citations.

**Say:**
> Every claim carries a citation. An independent judge scored faithfulness at
> zero point nine three, and it refused all twelve unanswerable questions in the
> eval.

**Do:** Type `What will Nvidia stock be worth in 2027?` Enter.

**Say:**
> The record cannot answer that, so it refuses and says why.

---

## 5. The scoreboard (2:50)

**Do:** Score tab.

**Say:**
> The evaluation ships inside the product. Seven rows. The first is day one,
> boolean search, zero point zero. The last is what runs right now, NDCG at ten
> of zero point five two.

**Say:**
> Four thousand six hundred judgments across a hundred queries, six labeling
> sessions. Each row is scored against its own corpus and judgment pool, so the
> rows are read one at a time.

---

## 6. Close (3:30)

**Say:**
> Fourteen hundred tests. Thirty three dollars of API spend. Dead source links
> measured at one percent and published.

**Say:**
> Two things it deliberately will not do. It gives no trading advice or signals.
> It mails nothing to an elected official without an explicit confirmation.

---

## Short version, 90 seconds

Beats 1, 3, and 6. Open on Search with one query and one receipt, spend the
middle on the Ledger, close on the tests, the cost, and the two limits.

## If something is slow on camera

> Semantic and hybrid take a few seconds against three hundred thousand
> documents.
