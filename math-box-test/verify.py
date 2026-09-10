import argparse
import csv
from pathlib import Path

#opencv
import cv2

#pdf-processing library
import fitz


# Render resolution
DPI = 150

# TeX uses scaled points
SP_PER_PT = 65536

def parse_args():
    parser = argparse.ArgumentParser(
        description="Render a PDF and draw recorded LaTeX math bounding boxes."
    )
    parser.add_argument("pdf", type=Path, help="compiled PDF to render")
    parser.add_argument("csv", type=Path, help="mathcoords.csv produced by LaTeX")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="directory for rendered images (defaults to the PDF directory)",
    )
    parser.add_argument("--dpi", type=int, default=DPI, help="render DPI")
    return parser.parse_args()


def main():
    args = parse_args()
    output_dir = args.output_dir or args.pdf.parent
    pixels_per_pt = args.dpi / 72.27

    # This is getting every single column and putting it in an array as a dictionary.
    annotations = []
    with args.csv.open(newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            annotations.append({
                "id": int(row["id"]),
                "page": int(row["page"]),
                "x": int(row["x"]),
                "y": int(row["y"]),
                "width": int(row["width"]),
                "height": int(row["height"]),
                "depth": int(row["depth"]),
            })

    print(f"Found {len(annotations)} annotations")

    # The DPI controls how many pixels are rendered per inch.
    pdf = fitz.open(args.pdf)
    page_count = len(pdf)
    output_dir.mkdir(parents=True, exist_ok=True)

    for page_index in range(page_count):
        page = pdf[page_index]
        pix = page.get_pixmap(dpi=args.dpi)
        original_path = output_dir / f"page_{page_index + 1}.png"
        pix.save(original_path)
        image = cv2.imread(str(original_path))
        image_height, image_width = image.shape[:2]
        print(f"Page {page_index + 1}: {image_width}x{image_height} pixels")

        for annotation in annotations:
            if annotation["page"] != page_index + 1:
                continue

            # Convert scaled points -> TeX points.
            x_pt = annotation["x"] / SP_PER_PT
            y_pt = annotation["y"] / SP_PER_PT
            width_pt = annotation["width"] / SP_PER_PT
            height_pt = annotation["height"] / SP_PER_PT
            depth_pt = annotation["depth"] / SP_PER_PT

            # Convert TeX points -> pixels.
            x = x_pt * pixels_per_pt
            y = y_pt * pixels_per_pt
            width = width_pt * pixels_per_pt
            height = height_pt * pixels_per_pt
            depth = depth_pt * pixels_per_pt

            x1 = int(x)
            x2 = int(x + width)

            # TeX's Y axis starts from the bottom; images start from the top.
            y_top_from_bottom = y + height
            y_bottom_from_bottom = y - depth
            y1 = int(image_height - y_top_from_bottom)
            y2 = int(image_height - y_bottom_from_bottom)

            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), 2)

        output_path = output_dir / f"page_{page_index + 1}_boxed.png"
        cv2.imwrite(str(output_path), image)
        print(f"Saved: {output_path}")

    pdf.close()
    print(f"Saved {page_count} rendered and boxed page pairs to {output_dir}")


if __name__ == "__main__":
    main()
