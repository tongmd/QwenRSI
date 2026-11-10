/* A human-written comparison, never a substitute for a model proposal. */
int policy(const int *s) {
    if (!s[0]) return 0;
    if (!s[1]) return 1;
    if (!s[2]) return 2;
    return 3;
}
int select_candidate(const int *s) {
    return s[1] > s[0] || (s[1] == s[0] && s[3] < s[2]);
}


#include <stdio.h>
int main(void) {
    int s[16]; for(int i=0;i<16;i++) if(scanf("%d", &s[i])!=1) return 2;
    printf("%d\n", s[15] ? select_candidate(s) : policy(s));
    return 0;
}
