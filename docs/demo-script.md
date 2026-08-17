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

> The retrieval stack is custom end to end. There is no RAG framework here and
> no vector database service. I wrote the inverted index, the BM25 scorer, the
> rank fusion, and the evaluation metrics. Two outside models do the two jobs I
> did not write myself. OpenAI text embedding three large builds the vectors,
> and Claude Opus writes the answers.

---

## 2. Search and receipts (0:25)

**Do:** Type `how much water does a data center use`. Enter. Lexical is selected.

**Say:**
> Keyword search over a positional inverted index I wrote. Postings hold the
> document, the term frequency, and the term positions in typed arrays. The
> BM25 scorer is mine, and a differential test checks it against a reference
> implementation on every committed query. The k1 and b parameters come from a
> hundred and twenty one point sweep.

**Do:** Click the receipt link on a county result. The hearing video opens at the timestamp.

**Say:**
> Every row carries a receipt. This one opens the hearing at the second those
> words were spoken.

**Do:** Return to the tab. Click Semantic. Then Hybrid.

**Say:**
> Same question, three retrieval modes. Semantic embeds the query with OpenAI
> text embedding three large at three thousand seventy two dimensions, then
> scores cosine similarity against three hundred thousand vectors held in
> memory. Hybrid fuses the two rankings with reciprocal rank fusion, bounded so
> the merge stays fast. On a long question semantic returns faster than keyword
> search, because every extra word is another posting list to merge.

> Every vector is cached under a hash of the model, the dimension, and the text.
> Growing the corpus only re-embeds the documents that are actually new.

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
> This retrieves first, then writes an answer that cites what it used. The
> retrieval, the prompt assembly, and the citation checking are all mine. The
> generator is Claude. The judge that scores it is a different model family on
> purpose, so nothing grades its own work.

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
> sessions. Precision, recall, MRR, and NDCG are implemented from scratch and
> pinned by tests. Each row is scored against its own corpus and judgment pool,
> so the rows are read one at a time.

> One of those rows dropped when I upgraded the embeddings. The new model was
> finding documents nobody had labeled yet, and unlabeled counts as wrong. I
> labeled its results and the score went up nineteen percent. That is the whole
> reason the pool grew six times.

---

## 6. Close (3:30)

**Say:**
> Fourteen hundred tests behind it. Dead source links measured at one percent
> and published on the page.

**Say:**
> All of this is public record already. The work was making it searchable and
> keeping every claim attached to the moment someone said it.

---

## Short version, 90 seconds

Beats 1, 3, and 6. Open on Search with one query and one receipt, spend the
middle on the Ledger, close on the tests and the measured link rot.

## If something is slow on camera

> Semantic and hybrid take a few seconds against three hundred thousand
> documents.
