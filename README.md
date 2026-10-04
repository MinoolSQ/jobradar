# jobradar

Više puta dnevno skupi nove IT oglase sa četiri izvora, a svako jutro Claude rutina oceni
ono što je novo prema profilu i pošalje mejl na matijatodo@gmail.com.

## Zašto je podeljeno na dva dela

Zakazana Claude rutina može da šalje mejl, ali ne može da otvori nijedan sajt: sandbox u
kom radi ima egress proxy koji spoljne domene odbija sa `connect_rejected`. Isto važi i za
`curl` i za WebFetch. Zato posao radi dvoje:

1. **GitHub Action** četiri puta dnevno pokrene `fetch_jobs.py`, skupi oglase iz poslednja
   tri dana i commituje `data/oglasi.json` u ovaj repo. Action ima normalan internet.
2. **Claude rutina** u 06:00 UTC klonira repo, pročita taj JSON, oceni oglase koji su prvi
   put viđeni u poslednjih 26 sati i pošalje jedan HTML mejl preko Resend-a, sa domena
   tablic.io.

Pošto rutina ne može da otvara oglase, skripta u JSON ubacuje i pun tekst svakog domaćeg
oglasa, 3500 karaktera, da bi ocena išla po stvarnim uslovima a ne po naslovu.

Rutina: `trig_01ULSuKkaRpqi42QMmqhcWYY`, pregled na https://claude.ai/code/routines

## Šta se traži

Dve vrste oglasa, u istom mejlu u odvojenim sekcijama:

- **Struka**: data inženjering, Python backend, DevOps i platform, cloud. Junior do
  medior, senior se preskače. Za svaki oglas rutina napiše i procenu koliko bi pripreme
  trebalo za baš tu poziciju.
- **Premošćavanje**: IT tehničar, sistem administrator, help desk, serviser, mrežni
  tehničar. Posao koji može odmah da se radi dok se ne nađe nešto u struci.

Detalji su u `profil.md`, koji nije u repou.

## Izvori

| Izvor | Kako se čita | Kako se zna šta je novo |
|---|---|---|
| poslovi.infostud.com | Sajt je Next.js, cela pretraga stoji kao JSON u `__NEXT_DATA__` bloku stranice. Trideset pretraga po ključnim rečima, svaka do četiri strane. | Polje `onlineViewDate` u samom oglasu |
| helloworld.rs | Server-renderovan HTML, parsira se regexom | Grub filter `vreme_postavljanja`, pa tačan `datePosted` iz JSON-LD bloka na stranici oglasa |
| remoteok.com | Javni JSON API | Polje `epoch` |
| weworkremotely.com | RSS, dva feeda | Polje `pubDate` |

Infostud i HelloWorld su iste kuće i dele ID-jeve oglasa, pa se duplikati izbacuju po ID-u.

Infostud oglas van IT kategorije prolazi ako mu naslov liči na IT posao (IT tehničar u
apoteci stoji pod drugom kategorijom).

Deo oglasa dolazi sa Remote OK, https://remoteok.com, čiji uslovi traže link nazad.

## Šta je novo, a šta već javljeno

Skripta pamti u `data/videno.json` kad je koji oglas prvi put videla i to upisuje u svaki
oglas kao `first_seen`. Rutina u mejl stavlja samo oglase sa `first_seen` u poslednjih 26
sati, ostale samo prebroji. Zato nije bitno koliko puta dnevno Action radi ni koliko kasni,
i zato prozor može da bude tri dana: oglas koji je prvi put uhvaćen trećeg dana i dalje se
javi kao nov.

Tekst oglasa koji je već skinut u prethodnom pokretanju se prepisuje iz starog
`data/oglasi.json`, ne skida se ponovo.

## Fajlovi

| Fajl | Šta je | U repou |
|---|---|---|
| `fetch_jobs.py` | Skuplja oglase. Samo standardna biblioteka, ništa se ne instalira. | da |
| `.github/workflows/radar.yml` | Action koji pokreće skriptu i commituje rezultat. | da |
| `data/oglasi.json` | Poslednji rezultat, ovo rutina čita. | da, piše ga Action |
| `data/videno.json` | ID oglasa i kad je prvi put viđen, čuva se 45 dana. | da, piše ga Action |
| `data/arhiva/YYYY-MM-DD.json` | Arhiva po danima, poslednje pokretanje tog dana. | da |
| `routine_prompt.md` | Uputstvo rutini: kako da oceni, kako da napiše mejl, šta da ne radi. | da |
| `build_prompt.py` | Spaja uputstvo i profil u jedan prompt za rutinu. | da |
| `profil.md` | Po čemu se oglasi ocenjuju. Ovo menjaj kad se promeni šta tražiš. | ne, u `.gitignore` |

Profil namerno nije u repou, u njemu piše šta ne znaš i šta izbegavaš, a repo je javan.

## Probanje lokalno

```bash
python fetch_jobs.py --days 3 --out proba.json --seen proba-videno.json
```

Opcije: `--days N` za širi prozor, `--sources infostud,helloworld` za samo neke izvore,
`--no-details` da preskoči otvaranje pojedinačnih oglasa (mnogo brže dok se testira),
`--seen` da ne prlja pravi `data/videno.json`.

Action se može pokrenuti ručno sa GitHub-a, dugme "Run workflow" na kartici Actions.

## Kad se nešto promeni

- Izmena u `fetch_jobs.py` ili `radar.yml`: commit i push, Action sam pokupi.
- Izmena u `profil.md` ili `routine_prompt.md`: **ne stiže sama do rutine**, rutina nosi
  svoju kopiju u promptu. Posle izmene:
  1. `python build_prompt.py --out prompt.txt`
  2. Otvori rutinu na https://claude.ai/code/routines i zameni joj prompt sadržajem
     `prompt.txt`, ili reci Claude-u: "ažuriraj rutinu trig_01ULSuKkaRpqi42QMmqhcWYY
     novim promptom iz prompt.txt"

## Vreme

Action je zakazan za 01:23, 07:23, 13:23 i 19:23 UTC, ali GitHub ga u praksi pusti 4 do 6
sati kasnije (zato i ne radi samo jednom ujutru). Rutina je `0 6 * * *` UTC, 08:00 po
beogradskom vremenu dok traje letnje računanje, 07:00 od kraja oktobra. Pošto rutina
gleda `first_seen` a ne vreme fajla, sat tamo ili ovamo ne menja šta će biti javljeno.

## Ograničenja

- Infostud vraća 30 oglasa po strani. Skripta čita do četiri strane po ključnoj reči, dok
  su svi oglasi na strani unutar prozora. Ako neka pretraga napuni sve četiri, to se upiše
  u `errors` i stigne u mejl.
- HelloWorld ne daje datum objave u listi, a njihov filter prima samo 2, 3 i 7 dana. Zato
  skripta uzme najuži prozor pa proveri tačan datum na stranici svakog oglasa. Sa
  `--no-details` ta provera otpada i u rezultatu može biti oglasa starijih od traženog dana.
- Infostudov `summary` ponekad pripada drugom oglasu. Rutini je rečeno da ga ignoriše kad
  ima `details`.
- LinkedIn nije uključen, traži prijavljivanje i blokira automatsko čitanje.
- Joberty nije uključen, sajt je SPA i bez JavaScript-a vraća praznu stranicu.
