/* Controlled CPU load for DRAM-sensitivity A/B (bench/memab.py).
 *
 *     memhog <spin|mem> <duty 0..1> <seconds>
 *
 * Runs on one thread with a fixed duty cycle (on for duty * 2 ms of every 2 ms). "mem" streams a
 * copy between two 16 MiB buffers (well past the 6 MiB L3, so every line goes to DRAM); "spin" runs
 * an ALU loop over registers only. Both take the same CPU time from the game, so the fps difference
 * between them is what the DRAM traffic costs. Both touch the buffers first, so memory pressure is
 * the same. Prints the copy rate achieved in "mem" mode.
 * Build: gcc -O2 -o build/memhog bench/memhog.c
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define BUF (16u << 20)
#define CHUNK (64u << 10)
#define PERIOD_NS 2000000ll

static int64_t now(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000000000ll + ts.tv_nsec;
}

int main(int argc, char **argv)
{
    if (argc != 4)
    {
        fprintf(stderr, "usage: memhog <spin|mem> <duty> <seconds>\n");
        return 2;
    }
    int mem = !strcmp(argv[1], "mem");
    double duty = atof(argv[2]);
    int64_t end = now() + (int64_t)(atof(argv[3]) * 1e9);
    char *a = aligned_alloc(4096, BUF), *b = aligned_alloc(4096, BUF);
    memset(a, 1, BUF);
    memset(b, 2, BUF);
    uint64_t copied = 0, off = 0, x = 1;
    int64_t on_ns = (int64_t)(duty * PERIOD_NS), busy = 0;
    for (int64_t start = now(); start < end; start += PERIOD_NS)
    {
        int64_t stop = start + on_ns, t;
        while ((t = now()) < stop)
        {
            if (mem)
            {
                memcpy(b + off, a + off, CHUNK);
                copied += CHUNK;
                off = (off + CHUNK) % BUF;
            }
            else
            {
                for (int i = 0; i < 4096; i++)
                    x = x * 6364136223846793005ull + 1442695040888963407ull;
            }
        }
        busy += t - start;
        int64_t next = start + PERIOD_NS;
        if ((t = now()) < next)
        {
            struct timespec ts = { 0, next - t };
            nanosleep(&ts, NULL);
        }
    }
    printf("%s duty %.2f: copied %.2f GiB/s of on-time %.2f GiB/s (x=%llu)\n", argv[1], duty,
           copied / 1073741824.0 / atof(argv[3]), busy ? copied / 1.073741824 / busy : 0.0,
           (unsigned long long)(x & 1));
    return 0;
}
