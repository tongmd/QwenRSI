/* State: inspected, patched, verified, last_error, patch_attempts,
   steps_left, steps_used, reserved[8], mode.
   Actions: 0 inspect, 1 patch, 2 test, 3 finish, 4 abort.
   This deliberately incomplete seed skips verification. */
int policy(const int *s) {
    if (!s[0]) return 0;
    if (!s[1]) return 1;
    return 3;
}

/* Meta state: parent solved, candidate solved, parent steps, candidate steps.
   The external validation gate is independent of this editable selector. */
int select_candidate(const int *s) {
    return s[1] > s[0];
}


#include <stdio.h>
int main(void) {
    int s[16]; for(int i=0;i<16;i++) if(scanf("%d", &s[i])!=1) return 2;
    printf("%d\n", s[15] ? select_candidate(s) : policy(s));
    return 0;
}
