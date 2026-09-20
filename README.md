# jobradar

Svako jutro skupi nove IT oglase sa četiri izvora, oceni ih prema profilu i pošalje mejl
na matijatodo@gmail.com.

## Zašto je podeljeno na dva dela

Zakazana Claude rutina može da šalje mejl, ali ne može da otvori nijedan sajt: sandbox u
kom radi ima egress proxy koji spoljne domene odbija sa `connect_rejected`. Isto važi i za
`curl` i za WebFetch. Zato posao radi dvoje:

1. **GitHub Action** u 05:45 UTC pokrene `fetch_jobs.py`, skupi oglase i commituje
   `data/oglasi.json` u ovaj repo. Action ima normalan internet.
2. **Claude rutina** u 06:00 UTC klonira repo, pročita taj JSON, oceni oglase prema
   profilu i pošalje jedan HTML mejl preko Resend-a, sa domena tablic.io.

Pošto rutina ne može da otvara oglase, skripta u JSON ubacuje i pun tekst svakog domaćeg
oglasa, 3500 karaktera, da bi ocena išla po stvarnim uslovima a ne po naslovu.

Rutina: `trig_01ULSuKkaRpqi42QMmqhcWYY`, pregled na https://claude.ai/code/routines

## Izvori

| Izvor | Kako se čita | Kako se zna šta je novo |
|---|---|---|
| poslovi.infostud.com | Sajt je Next.js, cela pretraga stoji kao JSON u `__NEXT_DATA__` bloku stranice. Ide petnaest pretraga po ključnim rečima. | Polje `onlineViewDate` u samom oglasu |
| helloworld.rs | Server-renderovan HTML, parsira se regexom | Parametar `vreme_postavljanja` filtrira na serveru |
| remoteok.com | Javni JSON API | Polje `epoch` |
| weworkremotely.com | RSS, dva feeda | Polje `pubDate` |

Infostud i HelloWorld su iste kuće i dele ID-jeve oglasa, pa se duplikati izbacuju po ID-u.

Nema baze sa već viđenim oglasima. Svežina se čita iz datuma objave u samom oglasu, pa
rutina ne zavisi ni od kakvog stanja između pokretanja. Posledica: ako Action ne prođe dva
dana, ta dva dana se ne nadoknađuju sama.

Deo oglasa dolazi sa Remote OK, https://remoteok.com, čiji uslovi traže link nazad.

## Fajlovi

| Fajl | Šta je | U repou |
|---|---|---|
| `fetch_jobs.py` | Skuplja oglase. Samo standardna biblioteka, ništa se ne instalira. | da |
| `.github/workflows/radar.yml` | Dnevni Action koji pokreće skriptu i commituje rezultat. | da |
| `data/oglasi.json` | Poslednji rezultat, ovo rutina čita. | da, piše ga Action |
| `data/arhiva/YYYY-MM-DD.json` | Arhiva po danima. | da |
| `routine_prompt.md` | Uputstvo rutini: kako da oceni, kako da napiše mejl, šta da ne radi. | da |
| `build_prompt.py` | Spaja uputstvo i profil u jedan prompt za rutinu. | da |
| `profil.md` | Po čemu se oglasi ocenjuju. Ovo menjaj kad se promeni šta tražiš. | ne, ostaje lokalno |

Profil namerno nije u repou, u njemu piše šta ne znaš i šta izbegavaš.

## Probanje lokalno

```bash
python "C:/Users/matij/OneDrive/Desktop/poso/jobradar/fetch_jobs.py" --days 3 --out proba.json
```

Opcije: `--days N` za širi prozor, `--sources infostud,helloworld` za samo neke izvore,
`--no-details` da preskoči otvaranje pojedinačnih oglasa (mnogo brže dok se testira).

Action se može pokrenuti ručno sa GitHub-a, dugme "Run workflow" na kartici Actions.

## Kad se nešto promeni

- Izmena u `fetch_jobs.py` ili `radar.yml`: commit i push, Action sam pokupi.
- Izmena u `profil.md` ili `routine_prompt.md`: **ne stiže sama do rutine**, rutina nosi
  svoju kopiju u promptu. Posle izmene:
  1. `python build_prompt.py --out prompt.txt`
  2. Reci Claude-u: "ažuriraj rutinu trig_01ULSuKkaRpqi42QMmqhcWYY novim promptom iz prompt.txt"

## Vreme

Action je `15 5 * * *` UTC, rutina `0 6 * * *` UTC, što je 07:15 i 08:00 po beogradskom
vremenu dok traje letnje računanje. Od kraja oktobra to postaje 06:15 i 07:00, pa ako
smeta, oba treba pomeriti za sat unapred.

## Ograničenja

- Infostud vraća najviše 30 oglasa po ključnoj reči, bez paginacije. Za dnevni prozor je to
  više nego dovoljno.
- HelloWorld ne daje datum objave u listi, pa se filtriranje oslanja na njihov filter.
- LinkedIn nije uključen, traži prijavljivanje i blokira automatsko čitanje.
- Joberty nije uključen, sajt je SPA i bez JavaScript-a vraća praznu stranicu.
