from bs4 import BeautifulSoup
from datetime import datetime
from operator import itemgetter
# import requests # pdga page blocking me now...
# from selenium import webdriver
import cloudscraper
import re
import numpy as np

# features to add:
# what rounds you're dropping
# what rounds you're adding
# outlier rounds
# rating increase/decrease
# unique messages for milestones (highest rating, biggest increase, etc.)

pdga_number = input("Input your PDGA number\n")

# ratings detail page
url_detail = f'https://www.pdga.com/player/{pdga_number}/details'
# result_detail = requests.get(url_detail)
scraper_detail = cloudscraper.create_scraper()
res_detail = scraper_detail.get(url_detail)
doc_detail = BeautifulSoup(res_detail.text, "html.parser")

# main pdga player profile page
url_stats = f'https://www.pdga.com/player/{pdga_number}'
# result_stats = requests.get(url_stats)
scraper_stats = cloudscraper.create_scraper()
res_stats = scraper_stats.get(url_stats)
doc_stats = BeautifulSoup(res_stats.text, "html.parser")

# just grab the players current rating while we're here
rating_li = doc_stats.find("li", class_="current-rating")
current_rating_string = rating_li.get_text(strip=True)
current_rating = int(re.search(r"Current Rating:(\d+)", current_rating_string).group(1))

# get raings updates dates
url_updates = 'https://www.pdga.com/faq/ratings/when-updated'
# result_updates = requests.get(url_updates)
scraper_updates = cloudscraper.create_scraper()
res_updates = scraper_updates.get(url_updates)
doc_updates = BeautifulSoup(res_updates.text, "html.parser")

table = doc_updates.find('table')
# Extract rows from tbody
rows = table.find("tbody").find_all("tr")
# Extract the data into a list of dictionaries
ratings_schedule = []
for row in rows:
    cells = row.find_all("td")
    if len(cells) == 2:
        submission_date = cells[0].get_text(strip=True)
        publication_date = cells[1].get_text(strip=True)

        dt_submission = int(datetime.strptime(submission_date.strip(), "%B %d, %Y").timestamp())
        dt_publication = int(datetime.strptime(publication_date.strip(), "%B %d, %Y").timestamp())

        ratings_schedule.append({
            "deadline": dt_submission,
            "publication": dt_publication
        })

# convert to dt timestamp
def parse_pdga_date(date_str):
    if 'Date:' in date_str:
        date_str = date_str.split('Date: ')[1]
    try:
        # Check if it's a date range like "31-May to 1-Jun-2025"
        if "to" in date_str:
            _, end_part = date_str.split("to")
            end_part = end_part.strip()
            # Standardize format
            dt = datetime.strptime(end_part.strip(), "%d-%b-%Y")
        else:
            # Single date like "12-Oct-2024"
            dt = datetime.strptime(date_str.strip(), "%d-%b-%Y")
        return int(dt.timestamp())
    except Exception as e:
        return f"Invalid date: {date_str} ({e})"

#####################
# parse detail page #
#####################

# Find all table rows that represent tournaments
tournament_rows = doc_detail.find_all("tr")

# List to hold all tournament dictionaries
tournaments = []

for row in tournament_rows:
    tournament_cell = row.find("td", class_="tournament")
    if not tournament_cell:
        continue  # Skip rows that aren't tournament rows

    tournament = {}

    # Tournament name
    link = tournament_cell.find("a")
    if link:
        tournament["name"] = link.get_text(strip=True)
        tournament["link"] = link["href"]

    # Other fields
    fields = {
        "tier": "tier",
        "date": "date",
        "division": "division",
        "round": "round tooltip",
        "score": "score",
        "rating": "round-rating",
        "evaluated": "evaluated",
        "included": "included",
    }

    for key, class_name in fields.items():
        cell = row.find("td", class_=class_name)
        if cell:
            tournament[key] = cell.get_text(strip=True)
    
    tournament['timestamp'] = parse_pdga_date(tournament['date'])

    tournaments.append(tournament)

#########################
# parse new tournaments #
#########################

def get_ratings_from_tournament_page(href_link):
    url = f'https://www.pdga.com{href_link}'
    scraper = cloudscraper.create_scraper()
    res = scraper_detail.get(url)
    doc = BeautifulSoup(res.text, "html.parser")
    
    rows = doc.find_all('tr')

    ratings = []

    date = doc.find(class_='tournament-date').get_text(strip=True)
    timestamp = parse_pdga_date(date)

    for row in rows:
        pdga_td = row.find('td', class_='pdga-number')
        if pdga_td and pdga_td.get_text(strip=True) == pdga_number:
            rating_cells = row.find_all('td', class_='round-rating')
            for cell in rating_cells:
                rating_text = cell.get_text(strip=True)
                if rating_text:
                    ratings.append(rating_text)
            break
    
    return ratings, timestamp, date

# see if any tournaments on the "player statistics" page needs to be evaluated

# Find all rows inside the <tbody> that represent the second tournament structure
stats_rows = doc_stats.select("tbody tr")
# List to hold the second group of tournament dictionaries
tournaments_stats = []

for row in stats_rows:
    tournament = {}

    # Extract each cell by class
    place = row.find("td", class_="place")
    points = row.find("td", class_="points")
    tournament_td = row.find("td", class_="tournament")
    tier = row.find("td", class_="tier")
    dates = row.find("td", class_="dates")
    prize = row.find("td", class_="prize")

    if not tournament_td:
        continue    # skip initial rows

    # Fill the dictionary if the cells exist
    if place:
        tournament["place"] = place.get_text(strip=True)
    if points:
        tournament["points"] = points.get_text(strip=True)
    if tournament_td:
        new_link_tag = tournament_td.find("a")
        if new_link_tag:
            tournament["name"] = new_link_tag.get_text(strip=True)
            tournament["link"] = new_link_tag["href"].split('#')[0]
    if tier:
        tournament["tier"] = tier.get_text(strip=True)
    if dates:
        tournament["date"] = dates.get_text(strip=True)
        tournament['timestamp'] = parse_pdga_date(tournament['date'])
    if prize:
        tournament["prize"] = prize.get_text(strip=True)

    tournaments_stats.append(tournament)

tournament_ids = {t['link'] for t in tournaments}
new_tournaments = [t for t in tournaments_stats if t['link'] not in tournament_ids]

for tournament in new_tournaments:
    link = tournament['link']

    ratings, timestamp, date = get_ratings_from_tournament_page(link)

    for i, rating in enumerate(ratings):
        if i==0:
            tournament['rating'] = ratings[i]
            tournament['round'] = i+1
        else:
            tournament_copy = tournament.copy()
            tournament_copy['rating'] = ratings[i]
            tournament_copy['round'] = i+1
            new_tournaments.append(tournament_copy)

# see if there are any events that we just finished playing
# which would mean they won't show up on our player page yet

now_playing = doc_stats.find_all(class_='current-events')
recent_events = doc_stats.find_all(class_='recent-events')

for event in now_playing + recent_events:
    link = event.find('a')["href"]
    name = event.find('a').get_text(strip=True)

    ratings, timestamp, date = get_ratings_from_tournament_page(link)
    
    for i, rating in enumerate(ratings):
        new_tournaments.append(
            {
                'name': name,
                'rating': rating,
                'timestamp': timestamp,
                'date': date,
                'round': i+1
            }
        )

# calculate pdga rating

#  how far back are we counting rounds
for dates in ratings_schedule:
    if dates['deadline'] > int(datetime.now().timestamp()):
        next_update = dates['deadline']
        break
last_date = next_update - 31556952 # minus 1 year

used_rounds = new_tournaments + [t for t in tournaments if t['evaluated'] == 'Yes' and t['timestamp'] > last_date] # and t['included'] == 'Yes' -> don't need, I think we eval all dropped rounds manually

sorted_rounds = sorted(used_rounds, key=itemgetter('timestamp'), reverse=True)

ratings = [int(t['rating']) for t in tournaments]

avg = np.average(ratings)
drop_below = np.round(max(avg-100, avg-2.5*np.std(ratings)))
ratings_minus_dropped = [r for r in ratings if r >= drop_below]

if len(ratings_minus_dropped) < 8:
    pdga_rating = round(np.average(ratings_minus_dropped))
else:
    pdga_rating = round(np.average(ratings_minus_dropped + ratings_minus_dropped[:len(ratings_minus_dropped)//4]))
                        
rating_change = pdga_rating - current_rating
print(f'New rating: {pdga_rating} ({rating_change:+})')

outgoing_rounds = [t for t in tournaments if t['evaluated'] == 'Yes' and t['timestamp'] < last_date]
incoming_rounds = new_tournaments

print(f'\nRounds you are dropping:\n')
for rd in outgoing_rounds:
    name = rd['name']
    round_number = rd['round']
    rating = rd['rating']
    print(f'{name}, round {round_number}, rating: {rating}\n')

print(f'\nRounds you are adding:\n')
for rd in incoming_rounds:
    name = rd['name']
    round_number = rd['round']
    rating = rd['rating']
    print(f'{name}, round {round_number}, rating: {rating}\n')

