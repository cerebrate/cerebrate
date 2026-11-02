import feedparser
import httpx
import pathlib
import re
import os

root = pathlib.Path(__file__).parent.resolve()
GRAPHQL_ENDPOINT = "https://api.github.com/graphql"


TOKEN = os.environ.get("CEREBRATE_TOKEN", "")


def replace_chunk(content, marker, chunk):
    r = re.compile(
        r"<!\-\- {} starts \-\->.*<!\-\- {} ends \-\->".format(marker, marker),
        re.DOTALL,
    )
    chunk = "<!-- {} starts -->\n{}\n<!-- {} ends -->".format(marker, chunk, marker)
    return r.sub(chunk, content)


def make_query(after_cursor=None):
    return """
query {
  viewer {
    repositories(first: 100, privacy: PUBLIC, after:AFTER) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        name
        releases(last:1) {
          totalCount
          nodes {
            name
            publishedAt
            url
          }
        }
      }
    }
  }
}
""".replace(
        "AFTER", '"{}"'.format(after_cursor) if after_cursor else "null"
    )


def fetch_releases(oauth_token):
    repos = []
    releases = []
    repo_names = set()
    has_next_page = True
    after_cursor = None

    while has_next_page:
        response = httpx.post(
            GRAPHQL_ENDPOINT,
            json={"query": make_query(after_cursor)},
            headers={"Authorization": "Bearer {}".format(oauth_token)},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("errors"):
            raise RuntimeError("GitHub GraphQL errors: {}".format(data["errors"]))
        for repo in data["data"]["viewer"]["repositories"]["nodes"]:
            if repo["releases"]["totalCount"] and repo["name"] not in repo_names:
                repos.append(repo)
                repo_names.add(repo["name"])
                releases.append(
                    {
                        "repo": repo["name"],
                        "release": repo["releases"]["nodes"][0]["name"]
                        .replace(repo["name"], "")
                        .strip(),
                        "published_at": repo["releases"]["nodes"][0][
                            "publishedAt"
                        ].split("T")[0],
                        "url": repo["releases"]["nodes"][0]["url"],
                    }
                )
        has_next_page = data["data"]["viewer"]["repositories"]["pageInfo"][
            "hasNextPage"
        ]
        after_cursor = data["data"]["viewer"]["repositories"]["pageInfo"]["endCursor"]
    return releases


def fetch_blog_entries():
    entries = feedparser.parse("https://eldraeverse.com/rss/")["entries"]
    return [
        {
            "title": entry["title"],
            "url": entry["link"].split("#")[0],
            "published": entry["published"].split("T")[0],
        }
        for entry in entries
    ]


if __name__ == "__main__":
    readme = root / "README.md"
    releases = fetch_releases(TOKEN)
    releases.sort(key=lambda r: r["published_at"], reverse=True)
    md = "\n".join(
        [
            "* [{repo} {release}]({url}) - {published_at}".format(**release)
            for release in releases[:5]
        ]
    )
    readme_contents = readme.open().read()
    rewritten = replace_chunk(readme_contents, "releases", md)

    # Leave the existing section alone if the feed is unreachable or empty,
    # rather than blanking it out.
    entries = fetch_blog_entries()[:5]
    if entries:
        entries_md = "\n".join(
            ["* [{title}]({url}) - {published}".format(**entry) for entry in entries]
        )
        rewritten = replace_chunk(rewritten, "fiction", entries_md)
    else:
        print("Warning: no blog entries fetched; leaving fiction section unchanged")

    readme.open("w").write(rewritten)
