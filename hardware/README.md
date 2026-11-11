# Brama WiFi ↔ USB ze sterowaniem zasilaniem celu

Mały adapter: z jednej strony WiFi, z drugiej port USB-A (host), na którym
wisi urządzenie docelowe. Adapter włącza i wyłącza jego zasilanie, widzi jego
port szeregowy (CDC-ACM) i jego dysk (MSC).

Przypadek wzorcowy to płytka Nucleo podpięta kablem do ST-Linka: zdalny
power-cycle, programowanie przez wgranie `.bin` na dysk ST-Linka i rozmowa
przez VCP, bez komputera przy stanowisku.

**Stan: projekt na papierze.** Jest schemat w postaci netlisty i BOM. Nie ma
PCB, nic nie było zmontowane ani zmierzone. Lista rzeczy do sprawdzenia przed
zamówieniem jest na końcu.

## Pliki

| Plik | Co to jest |
|---|---|
| [`gen_netlist.py`](gen_netlist.py) | źródło schematu (elementy, piny, sieci) i kontrola spójności |
| `wifi-usb-gateway.net` | netlista KiCad, generowana; import w Pcbnew: File → Import → Netlist |
| `bom-jlcpcb.csv` | BOM w układzie kolumn JLCPCB, generowany |

Schemat zmienia się w `gen_netlist.py` i generuje od nowa
(`python3 gen_netlist.py`; `--check` sprawdza, czy pliki są aktualne). Skrypt
odrzuca pin bez sieci, pin na dwóch sieciach i sieć z jednym węzłem.

## Schemat blokowy

```
 barrel 5.5/2.1          odwrotna polaryzacja        +5V
 5 V ───────────── J1 ──► + odcięcie > ~6,3 V ──┬──────────────► U3 TPS2553 ──► VBUS_OUT ──► J2 USB-A
                          Q1, Q2, Q3, D1, D2    │                 EN  FAULT      │   ▲         (cel)
                                                │                 ▲    │         │   │
                                                ▼                 │    ▼         │  U4 ESD
                                          U2 AMS1117-3.3 ──► U1 ESP32-S3-WROOM-1 │   │
                                                              IO19/IO20 ─ D-/D+ ─┼───┘
                                                              ADC ◄── dzielniki VBUS_OUT, +5V
```

## Decyzje projektowe

**ESP32-S3-WROOM-1-N16R8 jako całość radia i hosta USB.** Układ ma wbudowany
kontroler USB OTG full-speed z PHY, więc host CDC+MSC i WiFi to jeden moduł z
certyfikowaną anteną, dostępny w bibliotece JLCPCB. STM32 nie ma radia WiFi;
wariant STM32 + osobny moduł radiowy to dwa układy i dwa firmware'y na ten sam
efekt. PSRAM 8 MB wystarcza, żeby obraz firmware'u celu przyjąć w całości do
pamięci, zanim trafi na dysk ST-Linka.

**Zasilanie celu przez TPS2553.** Klucz high-side z regulowanym ograniczeniem
prądu i wyjściem FAULT. `R6 = 24,9 kΩ` daje ograniczenie około 1,1 A (wzór z
karty katalogowej TI, do przeliczenia przy zmianie rezystora). `R7` ściąga EN
do masy, więc cel jest wyłączony przez cały start ESP32 i włącza go dopiero
firmware. `C9` (220 µF) spełnia wymóg ≥ 120 µF na porcie hosta, a stoi za
kluczem, więc ładuje się prądem ograniczonym. `R9` (1 kΩ) rozładowuje VBUS po
wyłączeniu; stała czasowa z samym `C9` to 0,22 s, a z pojemnością celu więcej,
dlatego firmware trzyma wyłączenie co najmniej 2 s i potwierdza je pomiarem
`VBUS_SENSE`.

**Wejście 5 V odporne na zły zasilacz.** Wtyk 5,5/2,1 to także najczęstszy
wtyk zasilaczy 12 V, a bez zabezpieczenia 12 V poszłoby prosto na VBUS celu.
`Q1` i `Q2` (AO3401A, wspólne źródło) stoją szeregowo: `Q1` blokuje odwróconą
polaryzację, `Q2` nadnapięcie. `D2` (5,6 V) z `R3` i `R2` otwiera `Q3` przy
około 6,3 V, a ten zwiera bramkę ze źródłem i zamyka oba tranzystory. `D1`
(10 V) chroni bramki, których granica to ±12 V. Koszt w normalnej pracy to
około 0,1 Ω szeregowo, czyli 0,1 V przy 1 A. Bezpiecznika nie ma: zwarcie na
porcie celu ogranicza TPS2553, a resztę zasilacz.

**3,3 V z LDO.** ESP32 bierze średnio około 100 mA, w szczytach nadawania do
500 mA; przy 1,7 V spadku to średnio 0,2 W w SOT-223. Przetwornica byłaby
sprawniejsza, ale to cztery elementy więcej i dławik na małej płytce.

**Programowanie samego adaptera przez UART0 (`J3`), potem OTA.** Jedyne PHY
USB modułu jest zajęte przez port hosta, więc pierwszy firmware wchodzi przez
`J3` (GND, 3V3, EN, IO0, TXD0, RXD0) z przejściówki USB-UART 3,3 V; `SW2`
(BOOT) i `SW1` (RESET) wprowadzają bootloader ręcznie. `J3` nie jest lutowane
w montażu, wystarczą pogo-piny albo listwa wlutowana ręcznie.

**`J4` dla celu bez ST-Linka.** Pomocniczy UART (IO17/IO18) i NRST (IO16,
sterować jako open-drain) przez rezystory 1 kΩ, żeby linie nie zasilały
wyłączonego celu przez jego diody zabezpieczające. Też nielutowane.

## Przypisanie GPIO

| GPIO | Sieć | Funkcja |
|---|---|---|
| IO19 / IO20 | `USB_DM` / `USB_DP` | host USB full-speed |
| IO6 | `TGT_PWR_EN` | 1 = zasilanie celu włączone |
| IO7 | `TGT_FAULT_N` | 0 = przeciążenie albo przegrzanie klucza |
| IO4 (ADC1_CH3) | `VBUS_SENSE` | napięcie na porcie celu, dzielnik 1:2 |
| IO5 (ADC1_CH4) | `VIN_SENSE` | napięcie szyny +5V, dzielnik 1:2 |
| IO15 | `LED_STAT` | dioda stanu |
| IO0 | `ESP_IO0` | przycisk BOOT, po starcie zwykły przycisk |
| IO16, IO17, IO18 | `TGT_NRST`, `TGT_UART_TX`, `TGT_UART_RX` | złącze `J4` |
| IO43 / IO44 | `ESP_TXD0` / `ESP_RXD0` | konsola i programowanie, `J3` |

Pomiary są na ADC1, bo ADC2 koliduje z radiem. IO35–IO37 zajmuje PSRAM modułu
N16R8, a IO3, IO45 i IO46 to piny konfiguracyjne startu; wszystkie zostają
niepodłączone.

## Montaż w JLCPCB

- Wszystkie elementy na jednej stronie. 46 elementów w montażu, 26 pozycji BOM.
- Jedyny element przewlekany to gniazdo `J1` (DC-005, C381116), montowane z tej
  samej strony. Wariant SMT tego gniazda to C319134; w wynikach wyszukiwania
  miał inny opis średnic, więc przed użyciem trzeba sprawdzić w karcie, że
  pasuje do wtyku 5,5/2,1.
- Kolumna „LCSC status" w BOM: `confirmed` to numer sprawdzony w 2026-11 w
  kartach JLCPCB/LCSC (moduł ESP32, TPS2553, AO3401A, AMS1117, gniazdo DC),
  `confirm` to numer z pamięci, `select` to pozycja do wybrania w bibliotece.
  Moduł ESP32 i TPS2553 to części „extended" (opłata za załadowanie podajnika).
- Footprinty gniazd i przycisków zależą od konkretnej części, więc w netliście
  mają znacznik `TODO:footprint_from_LCSC_part`.

Wskazówki do PCB (2 warstwy, 1,6 mm wystarczą): antena modułu na krawędzi
płytki, bez miedzi pod nią na obu warstwach; D+/D− jako para o równej długości,
`U4` tuż przy `J2`; `C9` przy `J2`, `C5`/`C6` przy pinie 3V3 modułu; pole miedzi
pod zakładką `U2`. Szacowany rozmiar około 30 × 60 mm, ogranicza go moduł
(18 × 25,5 mm) i dwa gniazda.

## Firmware (zarys, nienapisany)

ESP-IDF ma gotowe sterowniki klas hosta: `usb_host_cdc_acm` i `usb_host_msc`
(z montowaniem FAT przez VFS). Do zrobienia:

- port TCP przekazujący bajty z i do CDC celu (VCP przez sieć),
- przyjęcie pliku przez HTTP i zapis na dysk MSC celu (programowanie Nucleo),
- włączanie, wyłączanie i power-cycle celu, odczyt FAULT i obu napięć,
- OTA dla samego adaptera.

ST-Link jest urządzeniem złożonym (debug + MSC + CDC). Kontroler ESP32-S3 ma
8 kanałów hosta; CDC (3 endpointy), MSC (2) i EP0 mieszczą się w nich, o ile
firmware nie otwiera interfejsu debugowego.

## Do sprawdzenia przed zamówieniem

1. **Zabezpieczenie wejścia nie było symulowane ani mierzone.** Próg odcięcia
   zależy od kolana diody 5,6 V przy prądzie rzędu 0,1 mA, więc realnie wyjdzie
   gdzieś między 6 a 6,8 V. Sprawdzić zasilaczem laboratoryjnym na pierwszej
   sztuce: rampa 0 → 15 V, wpięcie 12 V na gorąco, odwrócona polaryzacja.
2. **ST-Link V3 na hoście full-speed.** Nucleo-H503/H533/H563 mają STLINK-V3EC,
   który jest urządzeniem high-speed. Powinien zejść do full-speed, ale tego
   nie sprawdziłem. Nucleo-G071 (ST-LINK/V2-1, full-speed) to bezpieczny
   pierwszy cel.
3. **Wzór na ograniczenie prądu TPS2553** i wartość `R6` potwierdzić w
   aktualnej karcie katalogowej.
4. **Numery LCSC** ze statusem `confirm` i `select`, oraz rozkład pinów gniazda
   USB-A (`J2`) i DC (`J1`) względem numerów pinów w netliście.
5. **Netlista nie była otwierana w KiCadzie** (w tym środowisku go nie ma);
   format jest standardowy, ale pierwszy import trzeba obejrzeć.
6. **Zasilacz 5 V co najmniej 2 A.** Adapter i cel razem mogą wziąć 1,5 A.
