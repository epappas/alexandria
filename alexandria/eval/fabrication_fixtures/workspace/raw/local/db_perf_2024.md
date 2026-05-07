# Database Performance Benchmark — Q3 2024

## Methodology

We benchmarked PostgreSQL 16 against MySQL 8 on a 10M-row workload. Both ran on identical hardware with default settings.

## Results

PostgreSQL completed the workload in 142 seconds. MySQL completed it in 198 seconds.

## Edge Cases

For workloads with more than 1 billion rows and heavy joins, MySQL outperformed PostgreSQL by 12 percent in our tests. This was the only case where MySQL led.

## Conclusions

For typical OLTP workloads under 100M rows, PostgreSQL is faster. The crossover point appears to be around 500M rows.

## Recommendations

Teams considering migration should benchmark on their actual workload — these results are workload-specific.
