// =====================================================================
// tomato-res pH probe holder — parametric CAD
// =====================================================================
// Parts (select with -D 'part="name"'):
//   body        — main holder: G1/2 BSP male below, M24x2 collar thread above
//   collar      — finger-tight compression collar (print cap-face DOWN)
//   dummy_plug  — seals the holder when the probe is out
//   thread_test — 15-minute print to verify BSP fit in YOUR bush first
//   body_cut    — visualization only: body cross-section
//
// MEASURE FIRST:
//   probe_od  — smooth section of your Atlas probe, with calipers
//   bsp_fit   — print thread_test; if too tight in the reducing bush,
//               increase by 0.1 and print again. Iterate on the coupon,
//               not the body.
//
// Material: ASA, 4 perimeters, 40% infill, 0.2 mm layers.
// Body + plug print upright as modeled. Collar prints as modeled
// (cap face on the bed).
// =====================================================================

include <BOSL2/std.scad>
include <BOSL2/threading.scad>

// PRINT: thread-down (as modeled). Everything self-supports EXCEPT the
// flange underside (washer seal face - cannot be chamfered, the tee rim
// sits there). Paint a support ring under the flange only.
part = "body";          // which part to render

// ------------------- measured / tunable parameters -------------------
probe_od   = 12.0;      // MEASURE your probe. Atlas consumer = ~12.0
bsp_fit    = 0.20;      // radial shrink on BSP male for print fit
$slop      = 0.30;      // internal thread clearance (BOSL2)
$fn        = 96;

// ------------------- derived dimensions: body ------------------------
bsp_major  = 20.955 - 2*bsp_fit;   // G1/2 male, print-adjusted
bsp_pitch  = 25.4/14;              // 14 TPI
bsp_len    = 16;                   // lengthened: engagement preserved
                                   // above/through the cone base

flange_af  = 34;   flange_h = 5;   // hex wrench flats (PTFE seals the
                                   // threads; no washer seat needed)
hex_cnr    = flange_af*2/sqrt(3);          // 39.26 corner circle
cone_h     = (hex_cnr - (20.955-0.4))/2;   // 45-deg rise, thread->hex
z_hex      = bsp_len + cone_h;             // ~25.4
barrel_d   = 30;
neck_d     = 24;   neck_pitch = 2; neck_len = 10;   // M24x2 collar thread

z_barrel   = z_hex + flange_h;           // ~30.4
z_neck     = 55;
z_top      = 65;

inlet_d    = 16;
chamber_d  = 22;
z_chamber0 = 26;
z_chamber1 = 48;
guide_d    = probe_od + 0.4;
z_guide1   = 56;                          // gland floor
pocket_d   = 17;                          // collar nose pocket

bleed_z    = 46;
bleed_hole = 5.1;                         // self-tap an M6 stainless in

// Whitworth 55-degree profile (pitch units), truncated crest/valley
whit = [[-0.4165,-0.64],[-0.0833,0],[0.0833,0],[0.4165,-0.64]];

// ------------------- derived dimensions: collar -----------------------
col_af     = 32;  col_h = 20;
col_cap_h  = 4;
col_hole   = probe_od + 0.6;
nose_od    = 16;  nose_id = probe_od + 0.8;
// modeled print-side-down: cap z0-4, nose z4->18.5, thread z7-20

// =====================================================================
module hexprism(af, h) cylinder(h=h, d=af*2/sqrt(3), $fn=6);

module body() {
  difference() {
    union() {
      // G1/2 BSP male thread
      up(bsp_len/2)
        generic_threaded_rod(d=bsp_major, l=bsp_len, pitch=bsp_pitch,
                             profile=whit, bevel1=true, anchor=CENTER);
      // 45-deg self-supporting circle->hex morph, flush with the flats
      hull() {
        up(bsp_len-0.01) cylinder(h=0.1, d=20.955-0.4+0.6);
        up(z_hex-0.1)    hexprism(flange_af, 0.1);
      }
      // hex wrench flats
      up(z_hex-0.05) hexprism(flange_af, flange_h+0.05);
      // main barrel
      up(z_barrel) cylinder(h=z_neck - z_barrel, d=barrel_d);
      // bleed boss with a grounded gusset: hulled down onto the flange
      // corner so every layer is supported from the flange top upward
      hull() {
        up(bleed_z) yrot(90) cylinder(h=19.5, d=13);
        up(z_barrel+0.2) yrot(90) cylinder(h=19.5, d=0.8);
      }
      // M24x2 collar thread
      up(z_neck + neck_len/2)
        threaded_rod(d=neck_d, l=neck_len, pitch=neck_pitch,
                     bevel2=true, anchor=CENTER);
    }
    // ---- internal fluid path ----
    down(0.1) cylinder(h=z_chamber0+0.2, d=inlet_d);          // inlet
    up(z_chamber0) cylinder(h=z_chamber1-z_chamber0-5.1, d=chamber_d); // chamber
    up(z_chamber1-5.2)                       // 45-deg self-supporting roof
      cylinder(h=5.3, d1=chamber_d, d2=guide_d);
    up(z_chamber1) cylinder(h=z_guide1-z_chamber1+0.1, d=guide_d); // guide
    up(z_guide1) cylinder(h=z_top-z_guide1+0.2, d=pocket_d);  // gland pocket
    up(z_top-1) cylinder(h=1.1, d1=pocket_d, d2=pocket_d+2);  // entry chamfer
    down(0.05) cylinder(h=1.5, d1=inlet_d+3, d2=inlet_d);     // inlet chamfer
    // bleed hole through boss into chamber
    up(bleed_z) yrot(90) cylinder(h=25, d=bleed_hole, center=false);
  }
}

module collar() {
  difference() {
    hexprism(col_af, col_h);
    // probe pass hole through the cap
    down(0.1) cylinder(h=col_cap_h+0.3, d=col_hole);
    // cavity above cap: relief bore then internal thread to the top
    up(col_cap_h) cylinder(h=3.2, d=21.5);
    up(7 + 6.5)
      threaded_rod(d=neck_d, l=13.2, pitch=neck_pitch,
                   internal=true, bevel2=true, anchor=CENTER);
  }
  // compression nose ring (grows from cap; tip chamfered)
  difference() {
    up(col_cap_h) tube(h=14.5, od=nose_od, id=nose_id, anchor=BOT);
    up(col_cap_h+13.5) cylinder(h=1.1, d1=nose_id, d2=nose_od-0.8); // 45deg tip
  }
}

module dummy_plug() {
  cylinder(h=4, d=20);                       // cap
  up(4) cylinder(h=58, d=probe_od);          // rod
  up(62-0.01) cylinder(h=1.5, d1=probe_od, d2=probe_od-3); // tip chamfer
}

module thread_test() {
  cylinder(h=3, d=26);                       // grip disc
  up(3+6) generic_threaded_rod(d=bsp_major, l=12, pitch=bsp_pitch,
                               profile=whit, bevel2=true, anchor=CENTER);
}

// ---------------------------------------------------------------------
if (part == "body")        body();
if (part == "collar")      collar();
if (part == "dummy_plug")  dummy_plug();
if (part == "thread_test") thread_test();
if (part == "body_cut")
  difference() { body(); translate([0,-50,-5]) cube([50,100,80]); }
