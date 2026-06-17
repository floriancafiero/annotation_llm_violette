Annotate the novel below using the five-dimensional relationship codebook.

Return a JSON object with:

- `novel_id`
- `title`
- `author`
- `year`
- `corpus_notes`
- `relations`

Only annotate relationships that are romantic, erotic, sexual, conjugal, desirous, or strongly ambiguous. Do not list ordinary social relations.

Use the exact labels from the schema. If no relevant relationship is found, return an empty `relations` array.

Novel metadata:

- novel_id: {novel_id}
- title: {title}
- author: {author}
- year: {year}

Novel text:

```text
{text}
```
