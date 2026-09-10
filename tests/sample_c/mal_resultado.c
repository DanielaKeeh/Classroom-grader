#include <stdio.h>
int main() {
    int a, b;
    scanf("%d", &a);
    scanf("%d", &b);
    printf("%d\n", a - b);  // resta en vez de suma, a proposito

    char operador;
    //no es igual esto 
    scanf("%c", &operador);

    //que esto 
    scanf(" %c", &operador);

    
    return 0;
}
