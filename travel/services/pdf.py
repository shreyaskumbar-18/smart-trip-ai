"""Comprehensive PDF export service for SmartTrip AI itineraries.

Generates a multi-page, formatted PDF itinerary document with trip metadata,
day-by-day attraction schedules, recommendation explanations, activity timings,
weather backup alternatives, and budget summaries.
"""
from datetime import timedelta
from io import BytesIO


def trip_pdf(trip):
    """Generate a formatted PDF for a Trip instance and return a BytesIO buffer."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    base_styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        parent=base_styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
        alignment=0,
        spaceAfter=4,
    )

    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#475569"),
        spaceAfter=12,
    )

    section_heading = ParagraphStyle(
        "SectionHeading",
        parent=base_styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#1e293b"),
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True,
    )

    day_heading = ParagraphStyle(
        "DayHeading",
        parent=base_styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#0369a1"),
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True,
    )

    cell_style = ParagraphStyle(
        "TableCell",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#1e293b"),
    )

    cell_bold = ParagraphStyle(
        "TableCellBold",
        parent=cell_style,
        fontName="Helvetica-Bold",
    )

    cell_muted = ParagraphStyle(
        "TableCellMuted",
        parent=cell_style,
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#64748b"),
    )

    cell_alt = ParagraphStyle(
        "TableCellAlt",
        parent=cell_style,
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#b45309"),
    )

    th_style = ParagraphStyle(
        "TableHeader",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.white,
    )

    story = []

    # 1. Header Banner
    story.append(Paragraph("SmartTrip AI — Travel Itinerary", title_style))
    dest_name = getattr(trip.destination, "name", "Destination")
    dest_state = getattr(trip.destination, "state", "")
    dest_str = f"{dest_name}, {dest_state}" if dest_state else dest_name
    story.append(Paragraph(f"<b>{trip.title}</b> · Exploring {dest_str}", subtitle_style))
    story.append(Spacer(1, 4))

    # 2. Trip Overview Table
    start_str = trip.start_date.strftime("%d %b %Y") if hasattr(trip.start_date, "strftime") else str(trip.start_date)
    end_str = trip.end_date.strftime("%d %b %Y") if hasattr(trip.end_date, "strftime") else str(trip.end_date)
    duration_str = f"{trip.days} Day{'s' if trip.days != 1 else ''}"

    overview_data = [
        [
            Paragraph("<b>Destination:</b>", cell_style),
            Paragraph(dest_str, cell_style),
            Paragraph("<b>Travel Dates:</b>", cell_style),
            Paragraph(f"{start_str} to {end_str} ({duration_str})", cell_style),
        ],
        [
            Paragraph("<b>Travelers:</b>", cell_style),
            Paragraph(f"{trip.travelers} person{'s' if trip.travelers != 1 else ''}", cell_style),
            Paragraph("<b>Travel Pace & Style:</b>", cell_style),
            Paragraph(f"{trip.pace.title()} pace · {trip.interest.title()}", cell_style),
        ],
        [
            Paragraph("<b>Total Budget:</b>", cell_style),
            Paragraph(f"₹{trip.budget:,}", cell_bold),
            Paragraph("<b>Estimated Spend:</b>", cell_style),
            Paragraph(f"₹{trip.estimated_total:,}", cell_bold),
        ],
    ]

    overview_table = Table(overview_data, colWidths=[100, 160, 110, 153])
    overview_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(overview_table)
    story.append(Spacer(1, 14))

    # 3. Day-by-Day Itinerary
    story.append(Paragraph("Day-by-Day Itinerary Schedule", section_heading))

    all_items = list(
        trip.items.select_related("attraction", "weather_alternative")
        .order_by("day_number", "start_time", "pk")
    )

    if not all_items:
        story.append(Paragraph("<i>No itinerary stops scheduled for this trip yet.</i>", cell_style))
    else:
        for day in range(1, trip.days + 1):
            day_items = [item for item in all_items if item.day_number == day]
            current_date = trip.start_date + timedelta(days=day - 1) if hasattr(trip.start_date, "strftime") else None
            date_label = current_date.strftime("%A, %d %B %Y") if current_date else f"Day {day}"

            day_block = []
            day_block.append(Paragraph(f"<b>Day {day}: {date_label}</b>", day_heading))

            if not day_items:
                day_block.append(Paragraph("<i>Leisure / Free time scheduled for this day.</i>", cell_muted))
                day_block.append(Spacer(1, 8))
                story.append(KeepTogether(day_block))
                continue

            table_rows = [
                [
                    Paragraph("Time", th_style),
                    Paragraph("Attraction & Category", th_style),
                    Paragraph("Recommendation Reason & Details", th_style),
                    Paragraph("Cost & Alternatives", th_style),
                ]
            ]

            for item in day_items:
                attraction = item.attraction
                time_str = item.start_time.strftime("%H:%M") if item.start_time else "—"

                # Attraction column
                cat_str = attraction.category.title() if attraction.category else "Attraction"
                dur_str = f"~{attraction.duration_hours}h" if attraction.duration_hours else ""
                meta_sub = f"{cat_str} {('· ' + dur_str) if dur_str else ''}"
                attr_html = f"<b>{attraction.name}</b><br/><font color='#64748b' size='7'>{meta_sub}</font>"

                # Reason column
                reason_text = item.reason or attraction.description or "Recommended based on destination highlights."
                if len(reason_text) > 220:
                    reason_text = reason_text[:217] + "..."
                reason_html = f"{reason_text}"

                # Cost & weather backup column
                cost_val = int(attraction.estimated_cost or 0)
                details = [f"Est. ₹{cost_val}"]
                if item.score:
                    details.append(f"Match: {item.score:.1f}/100")
                details_text = "<br/>".join(details)

                if item.weather_alternative:
                    details_text += f"<br/><font color='#b45309'><b>Weather backup:</b><br/>{item.weather_alternative.name}</font>"

                table_rows.append([
                    Paragraph(time_str, cell_bold),
                    Paragraph(attr_html, cell_style),
                    Paragraph(reason_html, cell_style),
                    Paragraph(details_text, cell_style),
                ])

            day_table = Table(
                table_rows,
                colWidths=[48, 140, 205, 130],
                repeatRows=1,
            )
            day_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e2e8f0")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]))

            day_block.append(day_table)
            day_block.append(Spacer(1, 10))
            story.append(KeepTogether(day_block))

    # 4. Budget Expenses (if any recorded)
    expenses = list(trip.expenses.all()) if hasattr(trip, "expenses") else []
    if expenses:
        exp_block = []
        exp_block.append(Paragraph("Recorded Trip Expenses", section_heading))
        exp_rows = [[
            Paragraph("Category", th_style),
            Paragraph("Description", th_style),
            Paragraph("Amount", th_style),
        ]]
        total_exp = 0
        for exp in expenses:
            total_exp += exp.amount
            exp_rows.append([
                Paragraph(exp.category.title(), cell_style),
                Paragraph(exp.description or "—", cell_style),
                Paragraph(f"₹{exp.amount:,}", cell_bold),
            ])
        exp_rows.append([
            Paragraph("<b>Total Recorded</b>", cell_bold),
            Paragraph("", cell_style),
            Paragraph(f"<b>₹{total_exp:,}</b>", cell_bold),
        ])
        exp_table = Table(exp_rows, colWidths=[130, 263, 130])
        exp_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e2e8f0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        exp_block.append(exp_table)
        exp_block.append(Spacer(1, 10))
        story.append(KeepTogether(exp_block))

    # 5. Footer Notice
    story.append(Spacer(1, 12))
    footer_text = (
        "Generated by SmartTrip AI. Feasibility scores, road routes and weather-adaptive alternatives "
        "are estimates designed to assist your journey planning. Verify opening hours and tickets locally."
    )
    story.append(Paragraph(footer_text, cell_muted))

    doc.build(story)
    buffer.seek(0)
    return buffer
