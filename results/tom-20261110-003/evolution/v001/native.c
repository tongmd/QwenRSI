int policy(const int *s) {
    if (!s) return 0;
    if (s[0] == 0) return 0; /* Not inspected */
    if (s[1] == 0) return 1; /* Not patched, try patch */
    if (s[2] == 0) return 2; /* Not verified, must test */
    if (s[3] != 0) return 4; /* Last error exists, abort */
    if (s[4] >= 5) return 4; /* Too many patch attempts, abort */
    return 3; /* Verified and clean, finish */
}

int select_candidate(const int *s) {
    if (!s) return 0;
    int parent_solved = s[0];
    int cand_solved = s[1];
    int parent_steps = s[2];
    int cand_steps = s[3];
    if (cand_solved > parent_solved) return 1;
    if (cand_solved == parent_solved && cand_steps < parent_steps) return 1;
    return 0;
}

#include <stdio.h>
int main(void) {
    int s[16]; for(int i=0;i<16;i++) if(scanf("%d", &s[i])!=1) return 2;
    printf("%d\n", s[15] ? select_candidate(s) : policy(s));
    return 0;
}
