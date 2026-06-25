"""
mock_api_football.py — Mock API-Football server for local development.

Mimics the real api-football.com endpoints so live_proxy.py works unchanged.
Point the proxy at this server via API_FOOTBALL_URL=http://localhost:5003.

Usage:
    python3 pipeline/mock_api_football.py          # starts on port 5003

Then in another terminal:
    API_FOOTBALL_KEY=mock API_FOOTBALL_URL=http://localhost:5003 python3 pipeline/live_proxy.py
"""

from flask import Flask, jsonify

app = Flask(__name__)

MOCK_FIXTURES = [
    {
        "fixture": {
            "id": 1489393,
            "referee": "Ismail Elfath, USA",
            "timezone": "UTC",
            "date": "2026-06-20T21:00:00+00:00",
            "timestamp": 1781989200,
            "venue": {"id": 1234, "name": "MetLife Stadium", "city": "East Rutherford"},
            "status": {"long": "First Half", "short": "1H", "elapsed": 34}
        },
        "league": {"id": 1, "name": "World Cup", "country": "World", "season": 2026, "round": "Group F - 2"},
        "teams": {
            "home": {"id": 25, "name": "Germany", "logo": "https://media.api-sports.io/football/teams/25.png"},
            "away": {"id": 108, "name": "Ivory Coast", "logo": "https://media.api-sports.io/football/teams/108.png"}
        },
        "goals": {"home": 0, "away": 1},
        "score": {
            "halftime": {"home": None, "away": None},
            "fulltime": {"home": None, "away": None}
        }
    },
    {
        "fixture": {
            "id": 1489394,
            "referee": "Facundo Tello, Argentina",
            "timezone": "UTC",
            "date": "2026-06-20T18:00:00+00:00",
            "timestamp": 1781978400,
            "venue": {"id": 5678, "name": "Lincoln Financial Field", "city": "Philadelphia"},
            "status": {"long": "Second Half", "short": "2H", "elapsed": 67}
        },
        "league": {"id": 1, "name": "World Cup", "country": "World", "season": 2026, "round": "Group E - 2"},
        "teams": {
            "home": {"id": 2, "name": "France", "logo": "https://media.api-sports.io/football/teams/2.png"},
            "away": {"id": 1530, "name": "Colombia", "logo": "https://media.api-sports.io/football/teams/1530.png"}
        },
        "goals": {"home": 2, "away": 1},
        "score": {
            "halftime": {"home": 1, "away": 0},
            "fulltime": {"home": None, "away": None}
        }
    },
    {
        "fixture": {
            "id": 1489395,
            "referee": "Clément Turpin, France",
            "timezone": "UTC",
            "date": "2026-06-20T18:00:00+00:00",
            "timestamp": 1781978400,
            "venue": {"id": 9012, "name": "Hard Rock Stadium", "city": "Miami"},
            "status": {"long": "Half Time", "short": "HT", "elapsed": 45}
        },
        "league": {"id": 1, "name": "World Cup", "country": "World", "season": 2026, "round": "Group G - 2"},
        "teams": {
            "home": {"id": 26, "name": "Brazil", "logo": "https://media.api-sports.io/football/teams/26.png"},
            "away": {"id": 1, "name": "Argentina", "logo": "https://media.api-sports.io/football/teams/1.png"}
        },
        "goals": {"home": 1, "away": 1},
        "score": {
            "halftime": {"home": 1, "away": 1},
            "fulltime": {"home": None, "away": None}
        }
    }
]

MOCK_EVENTS = {
    1489393: [
        {"time": {"elapsed": 23, "extra": None}, "team": {"id": 108, "name": "Ivory Coast"}, "player": {"id": 50011, "name": "Ange-Yoan Bonny"}, "assist": {"id": 50007, "name": "Amad Diallo"}, "type": "Goal", "detail": "Normal Goal", "comments": None},
    ],
    1489394: [
        {"time": {"elapsed": 12, "extra": None}, "team": {"id": 2, "name": "France"}, "player": {"id": 2010, "name": "Kylian Mbappé"}, "assist": {"id": 2009, "name": "Ousmane Dembélé"}, "type": "Goal", "detail": "Normal Goal", "comments": None},
        {"time": {"elapsed": 38, "extra": None}, "team": {"id": 1530, "name": "Colombia"}, "player": {"id": 3010, "name": "Luis Díaz"}, "assist": {"id": 3009, "name": "James Rodríguez"}, "type": "Goal", "detail": "Normal Goal", "comments": None},
        {"time": {"elapsed": 55, "extra": None}, "team": {"id": 2, "name": "France"}, "player": {"id": 2011, "name": "Bradley Barcola"}, "assist": {"id": 2010, "name": "Kylian Mbappé"}, "type": "Goal", "detail": "Normal Goal", "comments": None},
        {"time": {"elapsed": 61, "extra": None}, "team": {"id": 1530, "name": "Colombia"}, "player": {"id": 3002, "name": "Daniel Muñoz"}, "assist": None, "type": "Card", "detail": "Yellow Card", "comments": "Foul"},
    ],
    1489395: [
        {"time": {"elapsed": 30, "extra": None}, "team": {"id": 26, "name": "Brazil"}, "player": {"id": 4001, "name": "Vinícius Jr."}, "assist": {"id": 4002, "name": "Rodrygo"}, "type": "Goal", "detail": "Normal Goal", "comments": None},
        {"time": {"elapsed": 44, "extra": 1}, "team": {"id": 1, "name": "Argentina"}, "player": {"id": 5001, "name": "Lionel Messi"}, "assist": None, "type": "Goal", "detail": "Penalty", "comments": None},
    ],
}

MOCK_STATISTICS = {
    1489393: [
        {"team": {"id": 25, "name": "Germany"}, "statistics": [
            {"type": "Ball Possession", "value": "62%"}, {"type": "Total Shots", "value": 8}, {"type": "Shots on Goal", "value": 3},
            {"type": "Corner Kicks", "value": 4}, {"type": "Fouls", "value": 7}, {"type": "Yellow Cards", "value": 1},
        ]},
        {"team": {"id": 108, "name": "Ivory Coast"}, "statistics": [
            {"type": "Ball Possession", "value": "38%"}, {"type": "Total Shots", "value": 5}, {"type": "Shots on Goal", "value": 2},
            {"type": "Corner Kicks", "value": 1}, {"type": "Fouls", "value": 9}, {"type": "Yellow Cards", "value": 2},
        ]},
    ],
    1489394: [
        {"team": {"id": 2, "name": "France"}, "statistics": [
            {"type": "Ball Possession", "value": "55%"}, {"type": "Total Shots", "value": 14}, {"type": "Shots on Goal", "value": 6},
            {"type": "Corner Kicks", "value": 5}, {"type": "Fouls", "value": 10}, {"type": "Yellow Cards", "value": 0},
        ]},
        {"team": {"id": 1530, "name": "Colombia"}, "statistics": [
            {"type": "Ball Possession", "value": "45%"}, {"type": "Total Shots", "value": 9}, {"type": "Shots on Goal", "value": 4},
            {"type": "Corner Kicks", "value": 3}, {"type": "Fouls", "value": 12}, {"type": "Yellow Cards", "value": 1},
        ]},
    ],
    1489395: [
        {"team": {"id": 26, "name": "Brazil"}, "statistics": [
            {"type": "Ball Possession", "value": "52%"}, {"type": "Total Shots", "value": 7}, {"type": "Shots on Goal", "value": 3},
            {"type": "Corner Kicks", "value": 3}, {"type": "Fouls", "value": 8}, {"type": "Yellow Cards", "value": 1},
        ]},
        {"team": {"id": 1, "name": "Argentina"}, "statistics": [
            {"type": "Ball Possession", "value": "48%"}, {"type": "Total Shots", "value": 6}, {"type": "Shots on Goal", "value": 2},
            {"type": "Corner Kicks", "value": 2}, {"type": "Fouls", "value": 11}, {"type": "Yellow Cards", "value": 2},
        ]},
    ],
}

MOCK_LINEUPS = {
    1489393: [
        {
            "team": {"id": 25, "name": "Germany", "logo": "https://media.api-sports.io/football/teams/25.png",
                     "colors": {"player": {"primary": "ffffff", "number": "000000", "border": "ffffff"},
                                "goalkeeper": {"primary": "4f9b9c", "number": "ecede8", "border": "4f9b9c"}}},
            "formation": "4-2-3-1",
            "startXI": [
                {"player": {"id": 497, "name": "Manuel Neuer", "number": 1, "pos": "G", "grid": "1:1"}},
                {"player": {"id": 502, "name": "Joshua Kimmich", "number": 6, "pos": "D", "grid": "2:4"}},
                {"player": {"id": 972, "name": "Jonathan Tah", "number": 4, "pos": "D", "grid": "2:3"}},
                {"player": {"id": 26243, "name": "Nico Schlotterbeck", "number": 15, "pos": "D", "grid": "2:2"}},
                {"player": {"id": 280074, "name": "Nathaniel Brown", "number": 18, "pos": "D", "grid": "2:1"}},
                {"player": {"id": 637, "name": "Felix Nmecha", "number": 23, "pos": "M", "grid": "3:2"}},
                {"player": {"id": 328033, "name": "Aleksandar Pavlović", "number": 5, "pos": "M", "grid": "3:1"}},
                {"player": {"id": 644, "name": "Leroy Sané", "number": 19, "pos": "M", "grid": "4:3"}},
                {"player": {"id": 25197, "name": "Jamal Musiala", "number": 10, "pos": "M", "grid": "4:2"}},
                {"player": {"id": 1100, "name": "Florian Wirtz", "number": 17, "pos": "M", "grid": "4:1"}},
                {"player": {"id": 987, "name": "Kai Havertz", "number": 7, "pos": "F", "grid": "5:1"}}
            ],
            "substitutes": [
                {"player": {"id": 498, "name": "Alexander Nübel", "number": 21, "pos": "G"}},
                {"player": {"id": 499, "name": "Oliver Baumann", "number": 12, "pos": "G"}},
                {"player": {"id": 24701, "name": "Malick Thiaw", "number": 24, "pos": "D"}},
                {"player": {"id": 521, "name": "Waldemar Anton", "number": 3, "pos": "D"}},
                {"player": {"id": 501, "name": "Antonio Rüdiger", "number": 2, "pos": "D"}},
                {"player": {"id": 24700, "name": "David Raum", "number": 22, "pos": "D"}},
                {"player": {"id": 350000, "name": "Assan Ouédraogo", "number": 25, "pos": "M"}},
                {"player": {"id": 640, "name": "Jamie Leweling", "number": 9, "pos": "F"}},
                {"player": {"id": 636, "name": "Nadiem Amiri", "number": 20, "pos": "M"}},
                {"player": {"id": 510, "name": "Pascal Groß", "number": 13, "pos": "M"}},
                {"player": {"id": 504, "name": "Leon Goretzka", "number": 8, "pos": "M"}},
                {"player": {"id": 638, "name": "Angelo Stiller", "number": 16, "pos": "M"}},
                {"player": {"id": 641, "name": "Maximilian Beier", "number": 14, "pos": "F"}},
                {"player": {"id": 642, "name": "Nick Woltemade", "number": 11, "pos": "F"}},
                {"player": {"id": 643, "name": "Deniz Undav", "number": 26, "pos": "F"}}
            ]
        },
        {
            "team": {"id": 108, "name": "Ivory Coast", "logo": "https://media.api-sports.io/football/teams/108.png",
                     "colors": {"player": {"primary": "ff6600", "number": "ffffff", "border": "ff6600"},
                                "goalkeeper": {"primary": "000000", "number": "ffffff", "border": "000000"}}},
            "formation": "4-1-4-1",
            "startXI": [
                {"player": {"id": 50001, "name": "Yahia Fofana", "number": 1, "pos": "G", "grid": "1:1"}},
                {"player": {"id": 50002, "name": "Wilfried Singo", "number": 5, "pos": "D", "grid": "2:4"}},
                {"player": {"id": 50003, "name": "Odilon Kossounou", "number": 7, "pos": "D", "grid": "2:3"}},
                {"player": {"id": 50004, "name": "Emmanuel Agbadou", "number": 20, "pos": "D", "grid": "2:2"}},
                {"player": {"id": 50005, "name": "Ghislain Konan", "number": 3, "pos": "D", "grid": "2:1"}},
                {"player": {"id": 50006, "name": "Ibrahim Sangaré", "number": 18, "pos": "M", "grid": "3:1"}},
                {"player": {"id": 50007, "name": "Amad Diallo", "number": 15, "pos": "M", "grid": "4:4"}},
                {"player": {"id": 50008, "name": "Franck Kessié", "number": 8, "pos": "M", "grid": "4:3"}},
                {"player": {"id": 50009, "name": "Christ Inao Oulaï", "number": 26, "pos": "M", "grid": "4:2"}},
                {"player": {"id": 50010, "name": "Yan Diomande", "number": 11, "pos": "M", "grid": "4:1"}},
                {"player": {"id": 50011, "name": "Ange-Yoan Bonny", "number": 9, "pos": "F", "grid": "5:1"}}
            ],
            "substitutes": [
                {"player": {"id": 50012, "name": "Alban Lafont", "number": 23, "pos": "G"}},
                {"player": {"id": 50013, "name": "Mohamed Koné", "number": 16, "pos": "G"}},
                {"player": {"id": 50014, "name": "Christopher Operi", "number": 13, "pos": "D"}},
                {"player": {"id": 50015, "name": "Ousmane Diomande", "number": 2, "pos": "D"}},
                {"player": {"id": 50016, "name": "Guéla Doué", "number": 17, "pos": "D"}},
                {"player": {"id": 50017, "name": "Evan Ndicka", "number": 21, "pos": "D"}},
                {"player": {"id": 50018, "name": "Bazoumana Touré", "number": 24, "pos": "F"}},
                {"player": {"id": 50019, "name": "Jean Michaël Seri", "number": 4, "pos": "M"}},
                {"player": {"id": 50020, "name": "Parfait Guiagon", "number": 25, "pos": "M"}},
                {"player": {"id": 50021, "name": "Seko Fofana", "number": 6, "pos": "M"}},
                {"player": {"id": 50022, "name": "Simon Adingra", "number": 10, "pos": "F"}},
                {"player": {"id": 50023, "name": "Oumar Diakité", "number": 14, "pos": "F"}},
                {"player": {"id": 50024, "name": "Elye Wahi", "number": 12, "pos": "F"}},
                {"player": {"id": 50025, "name": "Nicolas Pépé", "number": 19, "pos": "F"}},
                {"player": {"id": 50026, "name": "Evann Guessand", "number": 22, "pos": "F"}}
            ]
        }
    ],
    1489394: [
        {
            "team": {"id": 2, "name": "France", "logo": "https://media.api-sports.io/football/teams/2.png",
                     "colors": {"player": {"primary": "1e3a5f", "number": "ffffff", "border": "1e3a5f"},
                                "goalkeeper": {"primary": "ffcc00", "number": "000000", "border": "ffcc00"}}},
            "formation": "4-3-3",
            "startXI": [
                {"player": {"id": 2001, "name": "Mike Maignan", "number": 16, "pos": "G", "grid": "1:1"}},
                {"player": {"id": 2002, "name": "Jules Koundé", "number": 5, "pos": "D", "grid": "2:4"}},
                {"player": {"id": 2003, "name": "Dayot Upamecano", "number": 4, "pos": "D", "grid": "2:3"}},
                {"player": {"id": 2004, "name": "William Saliba", "number": 17, "pos": "D", "grid": "2:2"}},
                {"player": {"id": 2005, "name": "Théo Hernandez", "number": 22, "pos": "D", "grid": "2:1"}},
                {"player": {"id": 2006, "name": "N'Golo Kanté", "number": 13, "pos": "M", "grid": "3:3"}},
                {"player": {"id": 2007, "name": "Aurélien Tchouaméni", "number": 8, "pos": "M", "grid": "3:2"}},
                {"player": {"id": 2008, "name": "Manu Koné", "number": 6, "pos": "M", "grid": "3:1"}},
                {"player": {"id": 2009, "name": "Ousmane Dembélé", "number": 11, "pos": "F", "grid": "4:3"}},
                {"player": {"id": 2010, "name": "Kylian Mbappé", "number": 10, "pos": "F", "grid": "4:2"}},
                {"player": {"id": 2011, "name": "Bradley Barcola", "number": 7, "pos": "F", "grid": "4:1"}}
            ],
            "substitutes": [
                {"player": {"id": 2012, "name": "Alban Lafont", "number": 1, "pos": "G"}},
                {"player": {"id": 2013, "name": "Ibrahima Konaté", "number": 3, "pos": "D"}},
                {"player": {"id": 2014, "name": "Lucas Hernandez", "number": 21, "pos": "D"}},
                {"player": {"id": 2015, "name": "Malo Gusto", "number": 2, "pos": "D"}},
                {"player": {"id": 2016, "name": "Adrien Rabiot", "number": 14, "pos": "M"}},
                {"player": {"id": 2017, "name": "Warren Zaïre-Emery", "number": 18, "pos": "M"}},
                {"player": {"id": 2018, "name": "Désiré Doué", "number": 20, "pos": "M"}},
                {"player": {"id": 2019, "name": "Rayan Cherki", "number": 23, "pos": "F"}},
                {"player": {"id": 2020, "name": "Jean-Philippe Mateta", "number": 9, "pos": "F"}},
                {"player": {"id": 2021, "name": "Maghnes Akliouche", "number": 24, "pos": "M"}},
                {"player": {"id": 2022, "name": "Lucas Digne", "number": 19, "pos": "D"}},
                {"player": {"id": 2023, "name": "Ayyoub Bouaddi", "number": 25, "pos": "M"}},
                {"player": {"id": 2024, "name": "Maxence Lacroix", "number": 15, "pos": "D"}},
                {"player": {"id": 2025, "name": "Yehvann Diouf", "number": 26, "pos": "G"}},
                {"player": {"id": 2026, "name": "Elye Wahi", "number": 12, "pos": "F"}}
            ]
        },
        {
            "team": {"id": 1530, "name": "Colombia", "logo": "https://media.api-sports.io/football/teams/1530.png",
                     "colors": {"player": {"primary": "ffcc00", "number": "000066", "border": "ffcc00"},
                                "goalkeeper": {"primary": "00cc00", "number": "000000", "border": "00cc00"}}},
            "formation": "4-2-3-1",
            "startXI": [
                {"player": {"id": 3001, "name": "David Ospina", "number": 1, "pos": "G", "grid": "1:1"}},
                {"player": {"id": 3002, "name": "Daniel Muñoz", "number": 2, "pos": "D", "grid": "2:4"}},
                {"player": {"id": 3003, "name": "Yerry Mina", "number": 13, "pos": "D", "grid": "2:3"}},
                {"player": {"id": 3004, "name": "Davinson Sánchez", "number": 23, "pos": "D", "grid": "2:2"}},
                {"player": {"id": 3005, "name": "Johan Mojica", "number": 17, "pos": "D", "grid": "2:1"}},
                {"player": {"id": 3006, "name": "Richard Ríos", "number": 6, "pos": "M", "grid": "3:2"}},
                {"player": {"id": 3007, "name": "Jefferson Lerma", "number": 16, "pos": "M", "grid": "3:1"}},
                {"player": {"id": 3008, "name": "Jhon Arias", "number": 11, "pos": "M", "grid": "4:3"}},
                {"player": {"id": 3009, "name": "James Rodríguez", "number": 10, "pos": "M", "grid": "4:2"}},
                {"player": {"id": 3010, "name": "Luis Díaz", "number": 7, "pos": "M", "grid": "4:1"}},
                {"player": {"id": 3011, "name": "Jhon Córdoba", "number": 9, "pos": "F", "grid": "5:1"}}
            ],
            "substitutes": [
                {"player": {"id": 3012, "name": "Camilo Vargas", "number": 12, "pos": "G"}},
                {"player": {"id": 3013, "name": "Álvaro Montero", "number": 22, "pos": "G"}},
                {"player": {"id": 3014, "name": "Carlos Cuesta", "number": 3, "pos": "D"}},
                {"player": {"id": 3015, "name": "Cristian Borja", "number": 18, "pos": "D"}},
                {"player": {"id": 3016, "name": "Gustavo Puerta", "number": 15, "pos": "M"}},
                {"player": {"id": 3017, "name": "Kevin Castaño", "number": 5, "pos": "M"}},
                {"player": {"id": 3018, "name": "Juan Quintero", "number": 20, "pos": "M"}},
                {"player": {"id": 3019, "name": "Jorge Carrascal", "number": 14, "pos": "M"}},
                {"player": {"id": 3020, "name": "Rafael Borré", "number": 19, "pos": "F"}},
                {"player": {"id": 3021, "name": "Miguel Borja", "number": 21, "pos": "F"}},
                {"player": {"id": 3022, "name": "Jhon Durán", "number": 8, "pos": "F"}},
                {"player": {"id": 3023, "name": "Yaser Asprilla", "number": 24, "pos": "M"}},
                {"player": {"id": 3024, "name": "Juan Camilo Portilla", "number": 4, "pos": "D"}},
                {"player": {"id": 3025, "name": "Mateus Uribe", "number": 25, "pos": "M"}},
                {"player": {"id": 3026, "name": "Roger Martínez", "number": 26, "pos": "F"}}
            ]
        }
    ]
}

def _team_standing(rank, team_id, name, played, win, draw, lose, gf, ga):
    pts = win * 3 + draw
    return {
        "rank": rank,
        "team": {"id": team_id, "name": name, "logo": f"https://media.api-sports.io/football/teams/{team_id}.png"},
        "points": pts,
        "goalsDiff": gf - ga,
        "group": None,  # set by caller
        "form": None,
        "status": "same",
        "description": "Promotion - World Cup (Knockout stage)" if rank <= 2 else None,
        "all": {"played": played, "win": win, "draw": draw, "lose": lose, "goals": {"for": gf, "against": ga}},
    }

MOCK_STANDINGS = [
    {
        "league": {
            "id": 1, "name": "World Cup", "country": "World", "season": 2026,
            "standings": [
                [  # Group E — matchday 1 results: France 3-1 Japan, Colombia 2-0 Senegal
                    {**_team_standing(1, 2, "France", 1, 1, 0, 0, 3, 1), "group": "Group E"},
                    {**_team_standing(2, 1530, "Colombia", 1, 1, 0, 0, 2, 0), "group": "Group E"},
                    {**_team_standing(3, 12, "Japan", 1, 0, 0, 1, 1, 3), "group": "Group E"},
                    {**_team_standing(4, 1569, "Senegal", 1, 0, 0, 1, 0, 2), "group": "Group E"},
                ],
                [  # Group F — matchday 1 results: Germany 2-2 South Korea, Ivory Coast 1-0 Morocco
                    {**_team_standing(1, 108, "Ivory Coast", 1, 1, 0, 0, 1, 0), "group": "Group F"},
                    {**_team_standing(2, 25, "Germany", 1, 0, 1, 0, 2, 2), "group": "Group F"},
                    {**_team_standing(3, 17, "South Korea", 1, 0, 1, 0, 2, 2), "group": "Group F"},
                    {**_team_standing(4, 31, "Morocco", 1, 0, 0, 1, 0, 1), "group": "Group F"},
                ],
            ]
        }
    }
]

@app.route("/fixtures")
def fixtures():
    from flask import request
    fid = request.args.get("id", type=int)
    if fid:
        match = [f for f in MOCK_FIXTURES if f["fixture"]["id"] == fid]
        return jsonify({"response": match})
    return jsonify({"response": MOCK_FIXTURES})

@app.route("/fixtures/events")
def events():
    from flask import request
    fid = request.args.get("fixture", type=int)
    return jsonify({"response": MOCK_EVENTS.get(fid, [])})

@app.route("/fixtures/statistics")
def statistics():
    from flask import request
    fid = request.args.get("fixture", type=int)
    return jsonify({"response": MOCK_STATISTICS.get(fid, [])})

@app.route("/fixtures/lineups")
def lineups():
    from flask import request
    fixture_id = request.args.get("fixture", type=int)
    return jsonify({"response": MOCK_LINEUPS.get(fixture_id, [])})

@app.route("/standings")
def standings():
    return jsonify({"response": MOCK_STANDINGS})

if __name__ == "__main__":
    print("Mock API-Football server on port 5003 — 3 fake WC matches (GER-CIV 1H, FRA-COL 2H, BRA-ARG HT)")
    app.run(port=5003)
