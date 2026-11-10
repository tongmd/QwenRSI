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


volatile int input_state[16] __attribute__((section(".input"))) = {0};
static void emit(int x) {
    register int a0 __asm__("a0") = x;
    register int a7 __asm__("a7") = 1;
    __asm__ volatile("ecall" : : "r"(a0), "r"(a7) : "memory");
}
void _start(void) __attribute__((section(".text.init"), noreturn));
void _start(void) {
    int s[16]; for (int i=0; i<16; ++i) s[i]=input_state[i];
    int result = s[15] ? select_candidate(s) : policy(s);
    emit(result);
    register int a0 __asm__("a0") = 0;
    register int a7 __asm__("a7") = 93;
    __asm__ volatile("ecall" : : "r"(a0), "r"(a7) : "memory");
    for (;;) {}
}
