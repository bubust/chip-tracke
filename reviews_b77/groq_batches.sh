cd "/c/Users/牆泥袋溥/Desktop/claude-files/chip-b77"
S=reviews_b77
for f in jobs.py swr.py health.py warrant/calculator.py; do
  n=$(basename $f .py)
  PYTHONIOENCODING=utf-8 timeout 600 python ../claudex-review2.py --mode inspect --skip gemini --extra "$(cat $S/inspect_extra.txt)" --files $f --out $S/insp_groq_$n.json > $S/insp_groq_$n.txt 2>&1
  echo "== $f"; grep -v AFC $S/insp_groq_$n.txt | head -30
  sleep 65
done
echo ALL_DONE
