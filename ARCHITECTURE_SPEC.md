# SPECYFIKACJA ARCHITEKTURY I FUNKCJONALNOŚCI STRONY (WZÓR: SZYMONSARNECKI.PL)

## 1. CEL I CHARAKTERYSTYKA SERWISU
Strona osobista / marka osobista freelancera-programisty oferująca usługi tworzenia stron WWW, sklepów e-commerce, aplikacji dedykowanych oraz usług marketingu i SEO.

Główne cele biznesowe:
- Pozyskiwanie leadów (formularz wyceny, lead magnety, darmowe audyty, rezerwacja konsultacji).
- Budowanie autorytetu (case studies/realizacje, certyfikaty, opinie Google, statystyki, wpisy blogowe, kursy wideo).
- Transparentność oferty (cennik, jasny proces współpracy, opisy usług).

---

## 2. STRUKTURA I NAWIGACJA (PAGE HIERARCHY)

### A. Nagłówek (Header / Navigation)
- **Top Bar**: Dedykowany banner kontaktowy / promocja kursów (np. "Moje kursy 3 000+ kursantów | Blog | Cennik | e-mail | tel.").
- **Główne menu rozwijane (Mega Menu)**:
  1. *Strony i sklepy*: Strony firmowe WP, Landing Page, Sklepy WooCommerce, Konfiguratory 3D, Platformy e-learningowe, Aplikacje webowe, Systemy rezerwacji, CRM, Integracje & AI.
  2. *Opieka nad stroną*: Administracja WP, Odwirusowanie, Godziny programisty (stawka/h), Darmowy audyt, Optymalizacja szybkości.
  3. *Reklama i SEO*: Reklama w Mapach Google, Google Ads, Meta Ads, Pozycjonowanie SEO.
  4. *Realizacje*
  5. *O mnie*
  6. *Kontakt*
  7. *Przycisk Akcji (CTA)*: "Bezpłatna wycena" / "Zaloguj się" / "Koszyk"

### B. Strona Główna (Home Page) - Sekcje
1. **Hero Section**:
   - Chwytliwe nagłówek (Value Proposition)
   - Podtytuł z zakresem usług i obietnicą wartości
   - Przyciski CTA: "Bezpłatna wycena", "Zobacz realizacje"
   - Social proof (gwiazdki Google, liczba opinii, czas odpowiedzi)
2. **Sekcja "Co ma Ci dać nowa strona" / Wartości**:
   - Wzrost zapytań / Większa sprzedaż / Mniej ręcznej pracy
3. **Licznik i Statystyki**:
   - Lata doświadczenia, liczba wdrożeń, obsłużone rekordy w CRM, czas reakcji.
4. **Logotypy Klientów / Zaufali nam**:
   - Karuzela / siatka logotypów znanych marek.
5. **Kafelki Usług**:
   - Przegląd głównych pakietów wraz z cenami "od X zł netto".
6. **Wybrane Realizacje (Case Studies / Portfolio)**:
   - Filtrowalna siatka projektów (Strony, Sklepy, Konfiguratory, CRM).
   - Pokazanie rozwiązań na komputerze i telefonie + wyniki biznesowe (np. "+53% CTR").
7. **Reklama & SEO / Wyniki Kampanii**:
   - Statystyki z kampanii lokalnych/Google Ads (np. "231 telefonów z Map Google").
8. **O mnie / Dlaczego ja**:
   - Biografia, wyróżniki (rozmawiasz bezpośrednio z programistą, brak pośredników).
   - 3-etapowy proces współpracy.
9. **Materiały Edukacyjne / Kursy / Kanały Social Media**:
   - Linki do YouTube, TikTok, Instagram, LinkedIn.
   - Promocja kursów wideo z liczbą kursantów.
10. **Sekcja Opinii i Dowodu Społecznego**:
    - Widget z ocenami z Google My Business (gwiazdki + oryginalne treść opinii).
11. **Sekcja FAQ (Najczęściej Zadawane Pytania)**:
    - Akordeon z odpowiedziami na pytania o koszty, czas wykonania, własność kodu, gwarancję/opiekę.
12. **Najnowsze Wpisy na Blogu**:
    - Karty artykułów poradnikowych i eksperckich.
13. **Interaktywny Formularz Kontaktowy / Wycena**:
    - Nazwa firmy, imię, email, wybór typu projektu, przewidywany termin, opis.
14. **Pop-up / Widget "Darmowy Audyt Strony"**:
    - Szybki widget zbierający leady w zamian za audyt w 15 min.

### C. Podstrony
- `/strony-i-sklepy/` (i podstrony szczegółowe np. `/konfigurator-3d/`, `/systemy-crm/`)
- `/opieka-nad-strona/` (szczegóły pakietów abonamentowych)
- `/reklama-i-seo/`
- `/realizacje/` oraz podstrony pojedynczego case study (`/realizacje/{slug}/`)
- `/cennik/` (interaktywny kalkulator / tabele cenowe)
- `/blog/` oraz artykuły (`/blog/{slug}/`)
- `/moje-kursy/` (sklep z kursami wideo / LMS)
- `/o-mnie/`
- `/kontakt/`
- Regulamin, Polityka prywatności, Baner Cookie Consent.

---

## 3. ARCHITEKTURA TECHNICZNA I STACK TECHNOLOGICZNY

Istnieją dwa warianty wdrożenia takiej witryny:

### Wariant A: Headless / Modern Web Stack (Zalecany dla wydajności i elastyczności)
- **Frontend**: Next.js 14+ (React) lub Nuxt 3 (Vue) z Tailwind CSS.
- **Styling & UI**: Tailwind CSS + Shadcn UI / Radix UI + Framer Motion (płynne animacje, akordeony, mega menu).
- **Backend / CMS**: Strapi CMS, Payload CMS lub Sanity.io (do zarządzania realizacjami, blogiem, cennikiem, opiniami).
- **Formularze & Lead Generation**: React Hook Form + Zod (walidacja) + Resend / SendGrid (wysyłka powiadomień mailowych).
- **E-learning / Kursy**: Integracja z platformą kursową (np. WebToLearn, Teachable) lub moduł Next.js + Stripe/Przelewy24.
- **Analityka & Tracking**: Google Tag Manager, Google Analytics 4, Meta Pixel, Cookiebot / Consent Mode v2.

### Wariant B: Klasyczny WordPress Custom Theme (Tak jak na wzorcowej stronie)
- **CMS**: WordPress (Headless lub klasyczny z customowym motywem PHP/Twig - Timber).
- **E-Commerce**: WooCommerce (dla sprzedaży kursów).
- **Budowa Widoków**: Custom Gutenberg Blocks / ACF Pro (Advanced Custom Fields) – *bez ciężkich builderów typu Elementor*, dla maksymalnej szybkości.
- **Wtyczki**: ACF Pro, WP Rocket / LiteSpeed Cache, Yoast SEO / RankMath, WP Mail SMTP, Przelewy24 / PayU plugin.

---

## 4. KLUCZOWE FUNKCJONALNOŚCI INTERAKTYWNE

1. **Interaktywne Formularze Wyceny**:
   - Dynamiczne pola zależne od wybranej usługi.
   - Walidacja danych w czasie rzeczywistym.
   - Ochrona anti-spam (reCAPTCHA v3 lub Honeypot).

2. **Kalkulator Ceny / Cennik**:
   - Możliwość wyklikania opcji (np. liczba podstron, wersje językowe, e-commerce, integracja z CRM) i otrzymania szacunkowej kwoty przed wysłaniem formularza.

3. **Filtrowalna Galeria Realizacji (Portfolio)**:
   - Filtrowanie po kategorialnych tagach: Wszystkie, Strony WP, Sklepy WooCommerce, Systemy/CRM, Konfiguratory 3D.
   - Podgląd na makietach urządzeń (Desktop + Mobile).

4. **Widget / Pop-up Audytu**:
   - Formularz generujący zgłoszenie do darmowego audytu z timerem lub automatem mailowym.

5. **Banner RODO / Cookie Consent (GDPR)**:
   - Zgodny z Google Consent Mode v2 (zarządzanie zgodami na cookies analityczne i marketingowe).

6. **SEO & Structured Data (Schema.org)**:
   - Implementacja mikrodanych JSON-LD (`Organization`, `Person`, `Service`, `FAQPage`, `Article`, `LocalBusiness`).

---

## 5. PLAN WDROŻENIA / ROADMAPA

1. **Faza 1: Architektura i Content Plan** (Makiety UX, treści, schemat bazy danych).
2. **Faza 2: Design UI (Figma)** (Projekt graficzny RWD, system komponentów).
3. **Faza 3: Kodowanie Frontendu** (Strona główna, mega menu, responsywność, komponenty interaktywne).
4. **Faza 4: Integracja z CMS / Backendem** (Obsługa bloga, portfolio, formularzy wyceny i powiadomień mailowych).
5. **Faza 5: Optymalizacja SEO & Performance** (Core Web Vitals, optymalizacja obrazów WebP/AVIF, mikrodane).
6. **Faza 6: Testy, Wdrożenie i Analityka** (GTM, GA4, testy na urządzeniach mobilnych, uruchomienie).
