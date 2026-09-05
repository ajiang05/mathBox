import csv

#opencv
import cv2

#pdf-processing library
import fitz


PDF_FILE = "output.pdf"
CSV_FILE = "mathcoords.csv"

# Render resolution
DPI = 150

# TeX uses scaled points
SP_PER_PT = 65536

# There are 72.27 TeX points per inch
PIXELS_PER_PT = DPI / 72.27


# --------------------------------
# Read math coordinates
# --------------------------------
#This is getting every single column and putting it in array as dictionary
annotations = []

with open(CSV_FILE, newline="") as file:
    reader = csv.DictReader(file)

    for row in reader:
        annotations.append({
            "id": int(row["id"]),
            "page": int(row["page"]),
            "x": int(row["x"]),
            "y": int(row["y"]),
            "width": int(row["width"]),
            "height": int(row["height"]),
            "depth": int(row["depth"])
        })


print("Found annotations:")

for annotation in annotations:
    print(annotation)


# --------------------------------
# Open PDF
# --------------------------------
#This is reading the pdf. The DPI is how much pixels are in a 1x1 inch box, and basically controls resolution
#
pdf = fitz.open(PDF_FILE)


for page_index in range(len(pdf)):

    page = pdf[page_index]

    # Render PDF page
    pix = page.get_pixmap(dpi=DPI)

    original_path = f"page_{page_index + 1}.png"

    #T
    pix.save(original_path)

    image = cv2.imread(original_path)

    image_height, image_width = image.shape[:2]

    print()
    print(
        f"Page {page_index + 1}: "
        f"{image_width}x{image_height} pixels"
    )


    # --------------------------------
    # Draw each equation
    # --------------------------------

    for annotation in annotations:

        if annotation["page"] != page_index + 1:
            continue


        # Convert scaled points -> TeX points
        x_pt = annotation["x"] / SP_PER_PT +15
        y_pt = annotation["y"] / SP_PER_PT -12

        width_pt = annotation["width"] / SP_PER_PT
        height_pt = annotation["height"] / SP_PER_PT
        depth_pt = annotation["depth"] / SP_PER_PT


        # Convert TeX points -> pixels
        x = x_pt * PIXELS_PER_PT
        y = y_pt * PIXELS_PER_PT

        width = width_pt * PIXELS_PER_PT
        height = height_pt * PIXELS_PER_PT
        depth = depth_pt * PIXELS_PER_PT


        # --------------------------------
        # Build bounding box
        # --------------------------------

        x1 = int(x)
        x2 = int(x + width)

        # TeX's Y axis starts from the bottom.
        #
        # Images/OpenCV start from the top.
        #
        # Therefore we flip Y.

        y_top_from_bottom = y + height
        y_bottom_from_bottom = y - depth

        y1 = int(
            image_height - y_top_from_bottom
        )

        y2 = int(
            image_height - y_bottom_from_bottom
        )


        print(
            f"Math {annotation['id']}: "
            f"({x1}, {y1}) -> ({x2}, {y2})"
        )


        # --------------------------------
        # Draw debugging rectangle
        # --------------------------------

        cv2.rectangle(
            image,
            (x1, y1),
            (x2, y2),
            (0, 0, 255),
            2
        )


    # --------------------------------
    # Save result
    # --------------------------------

    output_path = (
        f"page_{page_index + 1}_boxed.png"
    )

    cv2.imwrite(output_path, image)

    print(f"Saved: {output_path}")