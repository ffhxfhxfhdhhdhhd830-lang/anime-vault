"""The 145 recommendations, represented once each in the shared catalog."""

from .models import title_document

CATALOG = {
    "romance_movies": ("movie", """Josee, the Tiger and the Fish
The Garden of Words
The Girl Who Leapt Through Time
To Every You I've Loved Before
To Me, the One Who Loved You
Hello World
Words Bubble Up Like Soda Pop
The Anthem of the Heart
Tamako Love Story
The Princess and the Pilot
Ride Your Wave
Kase-san and Morning Glories
The Place Promised in Our Early Days
Hotarubi no Mori e
Her Blue Sky
The Colors Within
Love Me, Love Me Not
Your Name
I Want to Eat Your Pancreas
A Silent Voice
Weathering With You
The Tunnel to Summer, the Exit of Goodbyes
5 Centimeters per Second"""),
    "action_fantasy_movies": ("movie", """Princess Mononoke
Howl's Moving Castle
Spirited Away
The Boy and the Heron
The First Slam Dunk
Sword of the Stranger
Promare
Redline
Dragon Ball Super: Broly
Jujutsu Kaisen 0"""),
    "psychological_movies": ("movie", """Perfect Blue
Paprika
Summer Wars
The Boy and the Beast
Expelled from Paradise
Patema Inverted
Time of Eve
The Empire of Corpses
Maboroshi"""),
    "action_adventure_series": ("tv_series", """Fullmetal Alchemist: Brotherhood
Hunter × Hunter (2011)
Bleach
One Piece
Black Clover
My Hero Academia
Chainsaw Man
Hell's Paradise
Kaiju No. 8
Solo Leveling
Fire Force
Mob Psycho 100
World Trigger
Yu Yu Hakusho
JoJo's Bizarre Adventure
Dandadan"""),
    "psychological_series": ("tv_series", """Death Note
Monster
Code Geass
Steins;Gate
Tomodachi Game
The Promised Neverland
Parasyte: The Maxim
Psycho-Pass
Erased
Terror in Resonance
Moriarty the Patriot
Link Click
Pluto
Odd Taxi
Bungo Stray Dogs
The Apothecary Diaries"""),
    "romance_series": ("tv_series", """Horimiya
The Dangers in My Heart
Kaguya-sama: Love Is War
My Dress-Up Darling
Komi Can't Communicate
The Fragrant Flower Blooms with Dignity
Blue Box
Makeine: Too Many Losing Heroines!
My Love Story with Yamada-kun at Lv999
Tsuki ga Kirei
Insomniacs After School
Golden Time
Toradora!
Lovely★Complex
Fruits Basket (2019)
The Angel Next Door Spoils Me Rotten
Our Dating Story: The Experienced You and The Inexperienced Me
A Sign of Affection"""),
    "fantasy_isekai_series": ("tv_series", """Frieren: Beyond Journey's End
Re:ZERO − Starting Life in Another World
That Time I Got Reincarnated as a Slime
Mushoku Tensei: Jobless Reincarnation
Overlord
KonoSuba
The Eminence in Shadow
Delicious in Dungeon
Made in Abyss
Ranking of Kings
The Rising of the Shield Hero
Dr. STONE
The Ancient Magus' Bride
To Your Eternity
The Faraway Paladin
The Wrong Way to Use Healing Magic"""),
    "comedy_slice_of_life_series": ("tv_series", """The Disastrous Life of Saiki K.
Grand Blue
Daily Lives of High School Boys
Nichijou
Bocchi the Rock!
Skip and Loafer
Hyouka
Barakamon
K-On!
Spy × Family
The Yuzuki Family's Four Sons
Laid-Back Camp
Wotakoi: Love Is Hard for Otaku
Welcome to Demon School! Iruma-kun"""),
    "sports_music_series": ("tv_series", """Haikyuu!!
Blue Lock
Kuroko's Basketball
Hajime no Ippo
Slam Dunk
Run with the Wind
Initial D
MF Ghost
Yuri!!! on Ice
Sound! Euphonium
Your Lie in April"""),
    "horror_thriller_series": ("tv_series", """Another
Higurashi: When They Cry
Shiki
Summertime Rendering
Heavenly Delusion
Dark Gathering
The Summer Hikaru Died
When They Cry: Gou
Corpse Party: Tortured Souls
The Perfect Insider
The Case Study of Vanitas
ID: INVADED"""),
}


def entries() -> list[dict]:
    result = {}
    for category, (format_, names) in CATALOG.items():
        for name in names.splitlines():
            name = name.strip()
            if not name:
                continue
            doc = title_document(name, category, format_)
            if name in result:
                result[name]["categories"].append(category)
            else:
                result[name] = doc
    result["The Promised Neverland"]["recommendation_tags"] = ["season_1"]
    return list(result.values())
