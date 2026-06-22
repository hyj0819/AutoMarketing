for i in `seq 1 10`;
do 
  python src/Twitter/run.py > log/twitter/2026-05-05/run_${i}.log
done